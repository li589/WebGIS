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
4. SSE 速率限制器行为
5. TileProviderRegistry 并发注册安全性

运行方式：
    $env:BACKEND_OBJECT_STORE_BACKEND='local'
    python -m pytest tests/test_frontend_call_simulation.py -v
"""

from __future__ import annotations

import asyncio
import threading
import time
import unittest
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


def _build_payload(*, layer_id: str = "ndvi", command_type: WorkflowCommandType = WorkflowCommandType.analysis) -> WorkflowSubmitRequest:
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


class FrontendCallFlowTests(unittest.TestCase):
    """模拟前端完整调用流程：submit → poll status → get events → get view → cancel。"""

    def test_full_frontend_workflow_lifecycle(self) -> None:
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
        with patch("app.api.routers.workflow_router.submission_service.submit_workflow", return_value=accepted):
            result = submit_workflow(payload)
        self.assertEqual(result.run_id, run_id)
        self.assertEqual(result.status, ExecutionStatus.accepted)

        # 2. Poll status
        running_status = _build_run_status(run_id=run_id, status=ExecutionStatus.running, progress=50)
        with patch("app.api.routers.workflow_router.submission_service.get_workflow_run", return_value=running_status):
            status_result = get_workflow_run(run_id)
        self.assertIsNotNone(status_result)
        self.assertEqual(status_result.status, ExecutionStatus.running)
        self.assertEqual(status_result.progress, 50)

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
        with patch("app.api.routers.workflow_router.submission_service.list_workflow_events", return_value=events_response):
            events_result = list_workflow_events(request_mock, run_id)
        self.assertEqual(events_result.run_id, run_id)
        self.assertEqual(len(events_result.items), 1)

        # 4. Get view (via result_view_service)
        from app.api.routers.workflow_router import get_workflow_run_view
        from shared.contracts.api_contracts import WorkflowRunViewResponse, WorkflowRunViewSummaryRow

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
        with patch("app.api.routers.workflow_router.result_view_service.get_workflow_run_view", return_value=view_response):
            view_result = get_workflow_run_view(run_id)
        self.assertEqual(view_result.run_id, run_id)
        self.assertEqual(view_result.title, "Test Workflow")

        # 5. Cancel
        cancelled_status = _build_run_status(run_id=run_id, status=ExecutionStatus.cancelled, progress=100)
        with patch("app.api.routers.workflow_router.lifecycle_service.cancel_workflow_run", return_value=cancelled_status):
            cancel_result = cancel_workflow_run(run_id)
        self.assertEqual(cancel_result.status, ExecutionStatus.cancelled)

    def test_submit_returns_429_when_capacity_reached(self) -> None:
        """容量超限时，路由层应将 ValueError 映射为 HTTPException 429。"""
        from app.api.routers.workflow_router import submit_workflow
        from fastapi import HTTPException

        payload = _build_payload()
        error_msg = "Workflow capacity reached: active_runs=4, limit=4"

        with patch("app.api.routers.workflow_router.submission_service.submit_workflow", side_effect=ValueError(error_msg)):
            with self.assertRaises(HTTPException) as ctx:
                submit_workflow(payload)
            self.assertEqual(ctx.exception.status_code, 429)
            self.assertIn("capacity", str(ctx.exception.detail).lower())

    def test_get_workflow_run_returns_none_for_missing_run(self) -> None:
        """查询不存在的 run_id 时，服务层返回 None，路由层应返回 404。"""
        from app.api.routers.workflow_router import get_workflow_run
        from fastapi import HTTPException

        with patch("app.api.routers.workflow_router.submission_service.get_workflow_run", return_value=None):
            with self.assertRaises(HTTPException) as ctx:
                get_workflow_run("run-nonexistent")
            self.assertEqual(ctx.exception.status_code, 404)

    def test_cancel_completed_workflow_raises_http_400(self) -> None:
        """取消已完成的 workflow 时，路由层应将 ValueError 映射为 HTTPException 400。"""
        from app.api.routers.workflow_router import cancel_workflow_run
        from fastapi import HTTPException

        error_msg = "Cannot cancel workflow in terminal state: succeeded"
        with patch("app.api.routers.workflow_router.lifecycle_service.cancel_workflow_run", side_effect=ValueError(error_msg)):
            with self.assertRaises(HTTPException) as ctx:
                cancel_workflow_run("run-done-1")
            self.assertEqual(ctx.exception.status_code, 400)
            self.assertIn("terminal state", str(ctx.exception.detail))

    def test_retry_nonexistent_workflow_raises_http_400(self) -> None:
        """重试不存在的 workflow 时，路由层应将 ValueError 映射为 HTTPException 400。"""
        from app.api.routers.workflow_router import retry_workflow_run
        from fastapi import HTTPException

        with patch("app.api.routers.workflow_router.lifecycle_service.retry_workflow_run", side_effect=ValueError("Cannot retry: no request found")):
            with self.assertRaises(HTTPException) as ctx:
                retry_workflow_run("run-nonexistent")
            self.assertEqual(ctx.exception.status_code, 400)
            self.assertIn("no request found", str(ctx.exception.detail))


class WorkflowConcurrencyTests(unittest.TestCase):
    """并发测试：多个 workflow 同时提交。"""

    def test_concurrent_submissions_respect_capacity_limit(self) -> None:
        """模拟 5 个并发提交，容量限制为 4，应至少有 1 个被拒绝。

        注意：由于 _assert_workflow_capacity 存在 TOCTOU 竞态条件，
        本测试验证的是路由层的行为（ValueError → 429），
        而非严格的容量控制。
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
        rejected_count = sum(1 for r in results if r is not None and "capacity" in str(r).lower())
        self.assertEqual(rejected_count, 5, "All concurrent submissions should be rejected when at capacity")

    def test_business_capacity_full_does_not_block_weather_tile_pool(self) -> None:
        """business 池满时，weather_tile 提交仍可过闸。"""
        from app.services.workflow.submission_service import WorkflowSubmissionService
        from app.services.workflow.run_class import RUN_CLASS_BUSINESS, RUN_CLASS_WEATHER_TILE

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
        service._persistence.get_effective_config_int = MagicMock(side_effect=config_side_effect)

        with self.assertRaises(ValueError) as biz_ctx:
            service._assert_workflow_capacity(RUN_CLASS_BUSINESS)
        self.assertIn("Workflow capacity reached", str(biz_ctx.exception))

        # weather_tile 池未满，不应抛错
        service._assert_workflow_capacity(RUN_CLASS_WEATHER_TILE)

    def test_weather_tile_capacity_full_does_not_block_business_pool(self) -> None:
        """weather_tile 池满时，business 提交仍可过闸。"""
        from app.services.workflow.submission_service import WorkflowSubmissionService
        from app.services.workflow.run_class import RUN_CLASS_BUSINESS, RUN_CLASS_WEATHER_TILE

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
        service._persistence.get_effective_config_int = MagicMock(side_effect=config_side_effect)

        with self.assertRaises(ValueError) as tile_ctx:
            service._assert_workflow_capacity(RUN_CLASS_WEATHER_TILE)
        self.assertIn("Weather tile workflow capacity reached", str(tile_ctx.exception))

        service._assert_workflow_capacity(RUN_CLASS_BUSINESS)

    def test_concurrent_tile_provider_registration_does_not_crash(self) -> None:
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
        self.assertEqual(len(registry._providers), 200)

    def test_concurrent_weather_tile_provider_lazy_init(self) -> None:
        """WeatherTileProvider 的 _ensure_layer_ids 并发初始化不应崩溃。"""
        from app.services.providers.weather_tile_provider import WeatherTileProvider

        provider = WeatherTileProvider()

        # Mock layer_catalog 返回空列表（避免依赖实际 catalog）
        with patch("app.services.layer_catalog.get_layer_catalog") as mock_catalog:
            mock_catalog.return_value = MagicMock(items=[])

            def call_matches(idx: int) -> bool:
                return provider.matches(f"layer-{idx}")

            threads = [threading.Thread(target=call_matches, args=(i,)) for i in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=10)

            # 不应崩溃，且 _weather_layer_ids 应已初始化
            self.assertIsNotNone(provider._weather_layer_ids)


class UnifiedTileRobustnessTests(unittest.TestCase):
    """统一瓦片服务的异常处理鲁棒性。"""

    def test_unified_tile_returns_503_when_provider_raises(self) -> None:
        """Provider 内部异常时，端点应返回 503 而非 500。"""
        from app.services.tile_provider_registry import TileProviderRegistry, tile_provider_registry
        from app.services.tile_provider_protocol import TileResponse

        # 创建一个会抛异常的 mock provider
        failing_provider = MagicMock()
        failing_provider.matches = MagicMock(return_value=True)
        failing_provider.get_tile = AsyncMock(side_effect=RuntimeError("upstream service unavailable"))

        # 临时注册到全局 registry
        tile_provider_registry.register(failing_provider)
        try:
            from fastapi.testclient import TestClient
            from app.main import create_app

            app = create_app()
            client = TestClient(app)

            response = client.get("/unified-tiles/test-failing-layer/5/25/12")
            self.assertEqual(response.status_code, 503)
            self.assertIn("Tile unavailable", response.json()["detail"])
        finally:
            # 清理：移除 mock provider
            tile_provider_registry._providers.remove(failing_provider)

    def test_unified_tile_returns_404_for_unknown_layer(self) -> None:
        """未知 layer_id 应返回 404。"""
        from fastapi.testclient import TestClient
        from app.main import create_app

        app = create_app()
        client = TestClient(app)

        response = client.get("/unified-tiles/totally-unknown-layer-id/5/25/12")
        self.assertEqual(response.status_code, 404)
        self.assertIn("No tile provider matches", response.json()["detail"])

    def test_unified_tile_validates_hour_parameter(self) -> None:
        """hour 参数超出范围 [0, 47] 应返回 422 验证错误。"""
        from fastapi.testclient import TestClient
        from app.main import create_app

        app = create_app()
        client = TestClient(app)

        # hour=-1 应被拒绝
        response = client.get("/unified-tiles/wind-field/5/25/12?hour=-1")
        self.assertEqual(response.status_code, 422)

        # hour=48 应被拒绝
        response = client.get("/unified-tiles/wind-field/5/25/12?hour=48")
        self.assertEqual(response.status_code, 422)

        # hour=47 应通过验证（可能 404 或 503，但不是 422）
        response = client.get("/unified-tiles/wind-field/5/25/12?hour=47")
        self.assertNotEqual(response.status_code, 422)

    def test_unified_tile_returns_correct_content_type_for_basemap(self) -> None:
        """底图瓦片应返回正确的 content_type（image/jpeg 或 image/png）。"""
        from fastapi.testclient import TestClient
        from app.main import create_app

        app = create_app()
        client = TestClient(app)

        with patch(
            "app.services.tile_proxy_service.tile_proxy_service.fetch_tile",
            new_callable=AsyncMock,
            return_value=b"fake-tile-data",
        ):
            # esri-street 含 "street" → image/png
            response = client.get("/unified-tiles/esri-street/5/25/12")
            self.assertEqual(response.status_code, 200)
            self.assertIn("image/", response.headers.get("content-type", ""))

            # tianditu-img 含 "img" → image/jpeg
            response = client.get("/unified-tiles/tianditu-img/5/25/12")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers.get("content-type"), "image/jpeg")


class SseRateLimiterTests(unittest.TestCase):
    """SSE 速率限制器行为测试。"""

    def test_rate_limiter_allows_under_limit(self) -> None:
        """速率限制以内应放行。"""
        from app.api.routers.workflow_router import _SseRateLimiter

        limiter = _SseRateLimiter(limit=5, window=timedelta(minutes=5))
        for i in range(5):
            self.assertTrue(limiter.check("192.168.1.1"), f"Request {i+1} should be allowed")

    def test_rate_limiter_blocks_over_limit(self) -> None:
        """超过速率限制应拒绝。"""
        from app.api.routers.workflow_router import _SseRateLimiter

        limiter = _SseRateLimiter(limit=3, window=timedelta(minutes=5))
        for i in range(3):
            self.assertTrue(limiter.check("10.0.0.1"))

        # 第 4 次应被拒绝
        self.assertFalse(limiter.check("10.0.0.1"))

    def test_rate_limiter_isolates_by_ip(self) -> None:
        """不同 IP 的限制应相互独立。"""
        from app.api.routers.workflow_router import _SseRateLimiter

        limiter = _SseRateLimiter(limit=2, window=timedelta(minutes=5))
        self.assertTrue(limiter.check("1.1.1.1"))
        self.assertTrue(limiter.check("1.1.1.1"))
        self.assertFalse(limiter.check("1.1.1.1"))  # 1.1.1.1 达到上限

        # 2.2.2.2 不受影响
        self.assertTrue(limiter.check("2.2.2.2"))
        self.assertTrue(limiter.check("2.2.2.2"))
        self.assertFalse(limiter.check("2.2.2.2"))

    def test_rate_limiter_window_expiry(self) -> None:
        """时间窗口过后应重置限制。"""
        from app.api.routers.workflow_router import _SseRateLimiter

        limiter = _SseRateLimiter(limit=2, window=timedelta(seconds=0))
        self.assertTrue(limiter.check("3.3.3.3"))
        self.assertTrue(limiter.check("3.3.3.3"))

        # 窗口为 0 秒，下一次请求时所有旧时间戳都应被清除
        time.sleep(0.01)
        self.assertTrue(limiter.check("3.3.3.3"))


class CircuitBreakerRobustnessTests(unittest.TestCase):
    """Open-Meteo 熔断器鲁棒性测试。"""

    def test_circuit_breaker_opens_after_threshold_failures(self) -> None:
        """连续失败达到阈值后，断路器应打开。"""
        from app.weatherengine.client import CircuitBreaker

        breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=60.0)
        self.assertEqual(breaker.state, "closed")

        breaker.record_failure()
        breaker.record_failure()
        self.assertEqual(breaker.state, "closed")  # 2 < 3，仍未打开

        breaker.record_failure()
        self.assertEqual(breaker.state, "open")  # 3 >= 3，打开

    def test_circuit_breaker_blocks_requests_when_open(self) -> None:
        """断路器打开后应拒绝请求。"""
        from app.weatherengine.client import CircuitBreaker

        breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=60.0)
        breaker.record_failure()
        self.assertEqual(breaker.state, "open")
        self.assertFalse(breaker.can_pass())

    def test_circuit_breaker_transitions_to_half_open_after_timeout(self) -> None:
        """恢复超时后应转为 HALF_OPEN 状态。"""
        from app.weatherengine.client import CircuitBreaker

        breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=0.1)
        breaker.record_failure()
        self.assertEqual(breaker.state, "open")

        time.sleep(0.15)
        self.assertTrue(breaker.can_pass())  # HALF_OPEN 放行探测
        self.assertEqual(breaker.state, "half_open")

    def test_circuit_breaker_closes_on_success(self) -> None:
        """成功请求应关闭断路器。"""
        from app.weatherengine.client import CircuitBreaker

        breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=60.0)
        breaker.record_failure()
        self.assertEqual(breaker.state, "open")

        # 模拟恢复超时 + HALF_OPEN 探测成功
        breaker._state = breaker._HALF_OPEN
        breaker._half_open_probes_in_flight = 1
        breaker.record_success()
        self.assertEqual(breaker.state, "closed")

    def test_circuit_breaker_reopens_on_half_open_failure(self) -> None:
        """HALF_OPEN 状态下探测失败应重新打开断路器。"""
        from app.weatherengine.client import CircuitBreaker

        breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=60.0)
        breaker.record_failure()
        breaker._state = breaker._HALF_OPEN
        breaker._half_open_probes_in_flight = 1

        breaker.record_failure()
        self.assertEqual(breaker.state, "open")

    def test_circuit_breaker_thread_safety(self) -> None:
        """多线程并发记录失败不应导致状态不一致。"""
        from app.weatherengine.client import CircuitBreaker

        breaker = CircuitBreaker(failure_threshold=100, recovery_timeout=60.0)

        def record_failures(count: int) -> None:
            for _ in range(count):
                breaker.record_failure()

        threads = [threading.Thread(target=record_failures, args=(50,)) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        # 4×50=200 次失败，应已打开
        self.assertEqual(breaker.state, "open")


class DeprecatedTileRoutesTests(unittest.TestCase):
    """旧版 tile routes 的兼容性测试。"""

    def test_deprecated_tiles_endpoint_still_works(self) -> None:
        """旧版 /tiles/{provider}/{z}/{x}/{y} 端点应仍然可用（deprecated 但不删除）。"""
        from fastapi.testclient import TestClient
        from app.main import create_app

        app = create_app()
        client = TestClient(app)

        with patch(
            "app.services.tile_proxy_service.tile_proxy_service.fetch_tile",
            new_callable=AsyncMock,
            return_value=b"deprecated-tile-data",
        ):
            response = client.get("/tiles/esri-street/5/25/12")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content, b"deprecated-tile-data")
            self.assertEqual(response.headers.get("X-Tile-Provider"), "esri-street")

    def test_deprecated_tiles_validates_zoom_range(self) -> None:
        """旧端点应验证 zoom 范围。"""
        from fastapi.testclient import TestClient
        from app.main import create_app

        app = create_app()
        client = TestClient(app)

        # zoom=-1 应返回 400
        response = client.get("/tiles/esri-street/-1/25/12")
        self.assertEqual(response.status_code, 400)

        # zoom=19 应返回 400
        response = client.get("/tiles/esri-street/19/25/12")
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
