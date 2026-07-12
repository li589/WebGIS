"""端到端业务回归验证脚本。

覆盖：
1. 共享工作流引擎 DAG 执行（真实节点拓扑、输入传递、错误处理）
2. 天气工作流端到端执行（forecast_fetch→point_parse→render→summary）
3. weather_point 上游消费修复验证（渲染节点不再冗余 API 调用）
4. workflow_tasks 调度分发（gee/weather/algorithm/download channel 路由）
5. 路由注册与可达性（diagnostics 不被遮蔽）
6. 配置一致性（队列名、enabled 开关、契约字段）
"""

from __future__ import annotations

import json
import sys
import traceback
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
from uuid import uuid4

# 确保路径
sys.path.insert(0, "..")

PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"

_results: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    status = f"{PASS} PASS" if condition else f"{FAIL} FAIL"
    msg = f"  {status} {name}"
    if detail:
        msg += f" — {detail}"
    print(msg)
    _results.append((name, condition, detail))


def section(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


# ============================================================
# 1. 共享工作流引擎 DAG 执行
# ============================================================
def test_workflow_engine_dag() -> None:
    section("1. 共享工作流引擎 DAG 执行")
    from app.workflow_engine import (
        BaseNode, NodeRegistry, WorkflowExecutor,
        WorkflowDefinition, NodeSpec, EdgeSpec, PortSpec,
        ExecutionContext, RunResult,
    )
    from app.workflow_engine.enums import PortKind, RunStatus

    # 构造两个测试节点：AddNode(a→result=a+step) → MulNode(result→final=result*factor)
    class AddNode(BaseNode):
        node_type = "test_add"
        def execute(self, inputs):
            from app.workflow_engine.models import NodeExecutionResult
            a = inputs.get("a", 0)
            step = inputs.get("step", 1)
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.completed,
                outputs={"result": a + step},
            )
        @staticmethod
        def build_spec():
            return NodeSpec(
                node_id="test_add", node_type="test_add",
                input_ports=[PortSpec(name="a"), PortSpec(name="step", required=False)],
                output_ports=[PortSpec(name="result")],
            )

    class MulNode(BaseNode):
        node_type = "test_mul"
        def execute(self, inputs):
            from app.workflow_engine.models import NodeExecutionResult
            result = inputs.get("result", 0)
            factor = inputs.get("factor", 2)
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.completed,
                outputs={"final": result * factor},
            )
        @staticmethod
        def build_spec():
            return NodeSpec(
                node_id="test_mul", node_type="test_mul",
                input_ports=[PortSpec(name="result"), PortSpec(name="factor", required=False)],
                output_ports=[PortSpec(name="final")],
            )

    registry = NodeRegistry()
    registry.register(AddNode)
    registry.register(MulNode)
    executor = WorkflowExecutor(registry)

    # 1a. 正常 DAG: a=3, step=4 → result=7 → factor=10 → final=70
    wf = WorkflowDefinition(
        workflow_id="test-dag",
        nodes=[
            NodeSpec(node_id="add", node_type="test_add", params={"a": 3, "step": 4}),
            NodeSpec(node_id="mul", node_type="test_mul", params={"factor": 10}),
        ],
        edges=[EdgeSpec(source_node_id="add", source_port="result", target_node_id="mul", target_port="result")],
    )
    ctx = ExecutionContext(workflow_id="test-dag")
    result = executor.execute(wf, ctx)

    check("DAG 正常执行 — status=completed", result.status == RunStatus.completed, f"status={result.status}")
    check("DAG 正常执行 — add.result=7", result.outputs.get("add.result") == 7, f"outputs={result.outputs}")
    check("DAG 正常执行 — mul.final=70", result.outputs.get("mul.final") == 70, f"outputs={result.outputs}")

    # 1b. 输入传递优先级：上游边 > 全局输入 > params
    wf2 = WorkflowDefinition(
        workflow_id="test-priority",
        inputs={"a": 100, "step": 200},  # 全局输入
        nodes=[
            NodeSpec(node_id="add", node_type="test_add", params={"a": 3, "step": 4}),  # params
        ],
    )
    result2 = executor.execute(wf2, ExecutionContext(workflow_id="test-priority"))
    # params 被全局输入覆盖: a=100, step=200 → result=300
    check("输入优先级 — 全局输入覆盖 params", result2.outputs.get("add.result") == 300, f"result={result2.outputs.get('add.result')}")

    # 1c. 循环依赖检测
    try:
        wf_cycle = WorkflowDefinition(
            workflow_id="test-cycle",
            nodes=[
                NodeSpec(node_id="a", node_type="test_add"),
                NodeSpec(node_id="b", node_type="test_mul"),
            ],
            edges=[
                EdgeSpec(source_node_id="a", source_port="result", target_node_id="b", target_port="result"),
                EdgeSpec(source_node_id="b", source_port="final", target_node_id="a", target_port="a"),
            ],
        )
        executor.topological_sort(wf_cycle.nodes, wf_cycle.edges)
        check("循环依赖检测 — 抛出 ValueError", False, "未抛出异常")
    except ValueError:
        check("循环依赖检测 — 抛出 ValueError", True)

    # 1d. 节点失败 + continue_on_error=False → 整体 FAILED
    class FailNode(BaseNode):
        node_type = "test_fail"
        def execute(self, inputs):
            from app.workflow_engine.models import NodeExecutionResult
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.failed,
                warnings=["intentional failure"],
            )
        @staticmethod
        def build_spec():
            return NodeSpec(node_id="test_fail", node_type="test_fail", output_ports=[PortSpec(name="out")])

    registry.register(FailNode)
    wf_fail = WorkflowDefinition(
        workflow_id="test-fail",
        nodes=[
            NodeSpec(node_id="f", node_type="test_fail"),
            NodeSpec(node_id="m", node_type="test_mul", params={"factor": 1}),
        ],
        edges=[EdgeSpec(source_node_id="f", source_port="out", target_node_id="m", target_port="result")],
    )
    result_fail = executor.execute(wf_fail, ExecutionContext(workflow_id="test-fail"))
    check("节点失败 — status=failed", result_fail.status == RunStatus.failed, f"status={result_fail.status}")
    check("节点失败 — errors 非空", len(result_fail.errors) > 0, f"errors={result_fail.errors}")


# ============================================================
# 2. 天气工作流端到端执行
# ============================================================
def test_weather_workflow_e2e() -> None:
    section("2. 天气工作流端到端执行")
    from app.weatherengine.workflow_service import WeatherWorkflowService
    from app.workflow_engine.enums import RunStatus

    svc = WeatherWorkflowService()

    # 验证节点注册
    node_types = svc.registry.supported_node_types()
    check("节点注册 — 6 个节点", len(node_types) == 6, f"nodes={node_types}")

    # 构造一个包含 summary_generate 的简单工作流（不依赖网络）
    # summary_generate 只需要 weather_point dict 输入，不需要 API 调用
    wf = {
        "workflow_id": "weather-e2e-test",
        "nodes": [
            {
                "node_id": "summary",
                "node_type": "weather_summary_generate",
                "params": {},
            },
        ],
        "inputs": {
            "weather_point": {
                "provider": "open-meteo",
                "layer_id": "wind-field",
                "model": "icon_seamless",
                "cache_status": "miss",
                "latitude": 23.13,
                "longitude": 113.26,
                "current": {"temperature_2m": 28.5, "wind_speed_10m": 5.2, "precipitation": 0.0},
                "hourly": [{"time": "2026-07-05T12:00", "temperature_2m": 28.5}],
                "render_hint": {"primary_metric": "wind_speed_10m", "unit_label": "m/s"},
                "summary": "风速 5.2 m/s",
            },
        },
    }

    result = svc.execute_workflow(wf)
    check("天气工作流 — status=completed", result.status == RunStatus.completed, f"status={result.status}")
    check("天气工作流 — summary 输出存在", "summary.summary" in result.outputs, f"outputs keys={list(result.outputs.keys())}")
    check("天气工作流 — summary 内容正确", result.outputs.get("summary.summary") == "风速 5.2 m/s", f"summary={result.outputs.get('summary.summary')}")
    check("天气工作流 — diagnostics 输出存在", "summary.diagnostics" in result.outputs, f"outputs keys={list(result.outputs.keys())}")

    # 验证诊断
    diag = svc.diagnose()
    check("诊断 — status=ok", diag.get("status") == "ok", f"diag={diag}")
    check("诊断 — supported_node_types 正确", "weather_forecast_fetch" in diag["node_registry"]["supported_node_types"])


# ============================================================
# 3. weather_point 上游消费修复验证
# ============================================================
def test_weather_point_upstream_consumption() -> None:
    section("3. weather_point 上游消费修复验证")
    from app.weatherengine.nodes import WindFieldRenderNode, TemperatureGridRenderNode, PrecipitationGridRenderNode, PointParseNode

    # 3a. 验证渲染节点的 build_spec 不再有 forecast 端口，改为 weather_point
    for cls in [WindFieldRenderNode, TemperatureGridRenderNode, PrecipitationGridRenderNode]:
        spec = cls.build_spec()
        port_names = [p.name for p in spec.input_ports]
        check(f"{cls.node_type} — 无 forecast 端口", "forecast" not in port_names, f"ports={port_names}")
        check(f"{cls.node_type} — 有 weather_point 端口", "weather_point" in port_names, f"ports={port_names}")
        # weather_point 应该是 required=False（支持独立运行）
        wp_port = next((p for p in spec.input_ports if p.name == "weather_point"), None)
        check(f"{cls.node_type} — weather_point required=False", wp_port and not wp_port.required, f"required={wp_port.required if wp_port else 'N/A'}")

    # 3b. PointParseNode 现在有 forecast 端口（M11 修复：消费上游 ForecastFetchNode 输出）
    pp_spec = PointParseNode.build_spec()
    pp_ports = [p.name for p in pp_spec.input_ports]
    check("PointParseNode — 有 forecast 端口", "forecast" in pp_ports, f"ports={pp_ports}")
    check("PointParseNode — forecast required=False", next((p for p in pp_spec.input_ports if p.name == "forecast"), None) is not None and not next(p for p in pp_spec.input_ports if p.name == "forecast").required, f"ports={pp_ports}")

    # 3c. 验证渲染节点在有 weather_point 输入时不调用 get_point_weather
    from app.workflow_engine.models import NodeSpec, ExecutionContext
    from app.weatherengine.nodes.wind_field_render import WindFieldRenderNode as WF

    mock_weather_point = {
        "provider": "open-meteo",
        "layer_id": "wind-field",
        "model": "icon_seamless",
        "cache_status": "hit",
        "latitude": 23.13,
        "longitude": 113.26,
        "current": {"temperature_2m": 28.5, "wind_speed_10m": 5.2},
        "hourly": [],
        "render_hint": {"primary_metric": "wind_speed_10m", "unit_label": "m/s"},
        "summary": "test",
    }

    spec = NodeSpec(node_id="wf-test", node_type="weather_wind_field", params={"latitude": 23.13, "longitude": 113.26})
    ctx = ExecutionContext(workflow_id="test")
    node = WF(spec, ctx)

    # m16 修复：节点通过 _utils.get_weather_engine_service() 获取 service，patch 路径同步更新
    with patch("app.weatherengine.nodes._utils.get_weather_engine_service") as mock_get_svc, \
         patch("app.weatherengine.nodes.wind_field_render.WeatherPointResponse") as mock_wpr:
        mock_svc = mock_get_svc.return_value
        # mock WeatherPointResponse.model_validate 以跳过 Pydantic 验证
        mock_wpr.model_validate = MagicMock(return_value=MagicMock())
        # 设置 mock：如果 get_point_weather 被调用，说明 weather_point 未被消费
        mock_svc.get_point_weather = MagicMock()
        mock_svc._build_wind_geojson = MagicMock(return_value={"type": "FeatureCollection", "features": []})
        mock_svc.build_wind_geojson = MagicMock(return_value={"type": "FeatureCollection", "features": []})

        result = node.execute({
            "weather_point": mock_weather_point,
            "latitude": 23.13,
            "longitude": 113.26,
        })

        check("weather_point 消费 — get_point_weather 未被调用", not mock_svc.get_point_weather.called,
              "get_point_weather should NOT be called when weather_point is provided")
        check("weather_point 消费 — WeatherPointResponse.model_validate 被调用", mock_wpr.model_validate.called,
              "should reconstruct WeatherPointResponse from upstream weather_point dict")
        check("weather_point 消费 — build_wind_geojson 被调用", mock_svc.build_wind_geojson.called,
              "should call _build_wind_geojson with reconstructed WeatherPointResponse")
        check("weather_point 消费 — status=completed", result.status.value == "completed", f"status={result.status}")


# ============================================================
# 4. workflow_tasks 调度分发
# ============================================================
def test_workflow_dispatch() -> None:
    section("4. workflow_tasks 调度分发")
    from app.tasks.workflow_tasks import resolve_workflow_channel, resolve_workflow_queue
    from app.core.config import settings
    from shared.contracts.api_contracts import (
        WorkflowSubmitRequest, WorkflowCommandType, WorkflowPriority,
        WorkflowResourceProfile, GeeWorkflowRequest, WeatherWorkflowRequest,
        AlgorithmWorkflowRequest, ClientIdentity,
    )

    # 4a. GEE 请求 → channel="gee", queue=gee-*
    gee_payload = WorkflowSubmitRequest(
        command_type=WorkflowCommandType.custom,
        client=ClientIdentity(),
        gee_request=GeeWorkflowRequest(workflow={"workflow_id": "test", "nodes": []}),
    )
    check("GEE 调度 — channel=gee", resolve_workflow_channel(gee_payload) == "gee")
    check("GEE 调度 — queue=gee-standard", resolve_workflow_queue(gee_payload) == settings.workflow_queue_gee_standard)

    # 4b. Weather 请求 → channel="weather", queue=weather-*
    weather_payload = WorkflowSubmitRequest(
        command_type=WorkflowCommandType.custom,
        client=ClientIdentity(),
        weather_request=WeatherWorkflowRequest(workflow={"workflow_id": "test", "nodes": []}),
    )
    check("Weather 调度 — channel=weather", resolve_workflow_channel(weather_payload) == "weather")
    check("Weather 调度 — queue=weather-standard", resolve_workflow_queue(weather_payload) == settings.workflow_queue_weather_standard)

    # 4c. Weather 请求 + realtime → queue=weather-realtime
    weather_realtime = WorkflowSubmitRequest(
        command_type=WorkflowCommandType.custom,
        client=ClientIdentity(),
        priority=WorkflowPriority.high,
        weather_request=WeatherWorkflowRequest(workflow={"workflow_id": "test", "nodes": []}),
    )
    check("Weather 调度 — realtime queue=weather-realtime",
          resolve_workflow_queue(weather_realtime) == settings.workflow_queue_weather_realtime)

    # 4d. Weather 请求 + batch → queue=weather-batch
    weather_batch = WorkflowSubmitRequest(
        command_type=WorkflowCommandType.custom,
        client=ClientIdentity(),
        resource_profile=WorkflowResourceProfile.batch,
        weather_request=WeatherWorkflowRequest(workflow={"workflow_id": "test", "nodes": []}),
    )
    check("Weather 调度 — batch queue=weather-batch",
          resolve_workflow_queue(weather_batch) == settings.workflow_queue_weather_batch)

    # 4e. download 请求 → channel="download"
    download_payload = WorkflowSubmitRequest(
        command_type=WorkflowCommandType.layer_preview,
        client=ClientIdentity(),
    )
    check("Download 调度 — channel=download", resolve_workflow_channel(download_payload) == "download")

    # 4f. 优先级：GEE > Weather > algorithm > analysis
    # GEE 和 Weather 同时存在时，GEE 优先
    both_payload = WorkflowSubmitRequest(
        command_type=WorkflowCommandType.custom,
        client=ClientIdentity(),
        gee_request=GeeWorkflowRequest(workflow={"workflow_id": "test", "nodes": []}),
        weather_request=WeatherWorkflowRequest(workflow={"workflow_id": "test", "nodes": []}),
    )
    check("优先级 — GEE > Weather", resolve_workflow_channel(both_payload) == "gee")


# ============================================================
# 5. 路由注册与可达性
# ============================================================
def test_routes() -> None:
    section("5. 路由注册与可达性")
    from app.main import app

    # 收集所有 weather 和 gee 路由
    all_routes = app.routes
    weather_routes = [(r.path, r.methods) for r in all_routes if getattr(r, "path", "").startswith("/weather/workflows")]
    gee_routes = [(r.path, r.methods) for r in all_routes if getattr(r, "path", "").startswith("/gee/")]

    check("Weather 路由 — 3 条", len(weather_routes) == 3, f"routes={weather_routes}")
    check("GEE 路由 — 存在", len(gee_routes) >= 5, f"gee routes count={len(gee_routes)}")

    # 验证 diagnostics 在 {workflow_name} 之前
    paths = [p for p, _ in weather_routes]
    diag_idx = next(i for i, p in enumerate(paths) if "diagnostics" in p)
    dyn_idx = next(i for i, p in enumerate(paths) if "{workflow_name}" in p)
    check("路由顺序 — diagnostics 在 {workflow_name} 之前", diag_idx < dyn_idx, f"diag_idx={diag_idx}, dyn_idx={dyn_idx}")

    # 验证 /weather/point 路由仍然存在（旧路由不丢失）
    has_weather_point = any(p == "/weather/point" for p, _ in [(r.path, r.methods) for r in all_routes if hasattr(r, 'path')])
    check("旧路由 — /weather/point 仍存在", has_weather_point)


# ============================================================
# 6. 配置一致性
# ============================================================
def test_config_consistency() -> None:
    section("6. 配置一致性")
    from app.core.config import settings

    # 6a. GEE 配置
    check("GEE — gee_enabled 存在", hasattr(settings, "gee_enabled"))
    check("GEE — gee_module_root 存在", hasattr(settings, "gee_module_root"))
    check("GEE — 4 个队列", all([
        settings.workflow_queue_gee_realtime == "gee-realtime",
        settings.workflow_queue_gee_standard == "gee-standard",
        settings.workflow_queue_gee_heavy == "gee-heavy",
        settings.workflow_queue_gee_batch == "gee-batch",
    ]))

    # 6b. Weather 配置
    check("Weather — weather_workflow_enabled 存在", hasattr(settings, "weather_workflow_enabled"))
    check("Weather — weather_workflow_enabled=true", settings.weather_workflow_enabled is True)
    check("Weather — 4 个队列", all([
        settings.workflow_queue_weather_realtime == "weather-realtime",
        settings.workflow_queue_weather_standard == "weather-standard",
        settings.workflow_queue_weather_heavy == "weather-heavy",
        settings.workflow_queue_weather_batch == "weather-batch",
    ]))

    # 6c. 共享契约
    from shared.contracts.api_contracts import (
        WorkflowSubmitRequest, GeeWorkflowRequest, WeatherWorkflowRequest,
    )
    import pydantic
    fields = WorkflowSubmitRequest.model_fields
    check("契约 — gee_request 字段存在", "gee_request" in fields)
    check("契约 — weather_request 字段存在", "weather_request" in fields)

    # 6d. WeatherWorkflowRequest 字段
    wf_fields = WeatherWorkflowRequest.model_fields
    check("契约 — WeatherWorkflowRequest.workflow 字段", "workflow" in wf_fields)
    check("契约 — WeatherWorkflowRequest.context 字段", "context" in wf_fields)

    # 6e. runtime_status_service runtime status 包含 weather_bridge_service
    from app.services.workflow.service_container import runtime_status_service
    status = runtime_status_service.get_runtime_status()
    service_names = [s.service_name for s in status.services]
    check("runtime_status_service — gee_bridge_service 注册", "gee_bridge_service" in service_names, f"services={service_names}")
    check("runtime_status_service — weather_bridge_service 注册", "weather_bridge_service" in service_names, f"services={service_names}")

    # 6f. 服务详情包含 weather/gee 队列配置
    weather_svc = next((s for s in status.services if s.service_name == "weather_bridge_service"), None)
    gee_svc = next((s for s in status.services if s.service_name == "gee_bridge_service"), None)
    if weather_svc and weather_svc.details:
        queues_str = json.dumps(weather_svc.details, ensure_ascii=False, default=str)
        check("weather 服务详情 — 队列配置存在", "weather-realtime" in queues_str or "queues" in weather_svc.details, f"details keys={list(weather_svc.details.keys())}")
    else:
        check("weather 服务详情 — 非空", False, "weather_svc details is empty")
    if gee_svc and gee_svc.details:
        queues_str = json.dumps(gee_svc.details, ensure_ascii=False, default=str)
        check("gee 服务详情 — 队列配置存在", "gee-realtime" in queues_str or "queues" in gee_svc.details, f"details keys={list(gee_svc.details.keys())}")
    else:
        check("gee 服务详情 — 非空", False, "gee_svc details is empty")


# ============================================================
# 7. weather_bridge_service 端到端
# ============================================================
def test_weather_bridge_e2e() -> None:
    section("7. weather_bridge_service 端到端")
    from app.services.weather_bridge_service import WeatherBridgeService
    from app.workflow_engine.models import RunResult, NodeExecutionResult
    from app.workflow_engine.enums import RunStatus
    from shared.contracts.api_contracts import (
        WorkflowSubmitRequest, WorkflowCommandType, WeatherWorkflowRequest,
        ClientIdentity, WorkflowPriority,
    )

    service = WeatherBridgeService()

    # 构造一个 weather_request payload
    payload = WorkflowSubmitRequest(
        command_type=WorkflowCommandType.custom,
        layer_id="wind-field",
        priority=WorkflowPriority.normal,
        client=ClientIdentity(),
        weather_request=WeatherWorkflowRequest(
            workflow={
                "workflow_id": "bridge-e2e-test",
                "nodes": [
                    {"node_id": "summary", "node_type": "weather_summary_generate", "params": {}},
                ],
                "inputs": {
                    "weather_point": {
                        "provider": "open-meteo",
                        "layer_id": "wind-field",
                        "model": "test",
                        "cache_status": "hit",
                        "latitude": 23.0,
                        "longitude": 113.0,
                        "current": {"wind_speed_10m": 3.5},
                        "hourly": [],
                        "render_hint": {"primary_metric": "wind_speed_10m", "unit_label": "m/s"},
                        "summary": "风速 3.5 m/s",
                    },
                },
            },
            workflow_id="bridge-e2e-test",
        ),
    )

    # supports 应返回 True
    check("bridge supports — True", service.supports(payload))

    # 执行
    def event_factory(channel="log", message="", progress=0, payload=None):
        from shared.contracts.api_contracts import WorkflowEvent, EventChannel, LogLevel
        return WorkflowEvent(
            event_id=f"evt-{uuid4().hex[:8]}",
            run_id="test-run",
            channel=EventChannel(channel),
            level=LogLevel.info,
            message=message,
            created_at=datetime.now(timezone.utc),
            progress=progress,
            payload=payload or {},
        )

    result = service.execute(
        run_id="run-bridge-test",
        payload=payload,
        requested_at=datetime.now(timezone.utc),
        event_factory=event_factory,
    )

    check("bridge execute — message 包含天气工作流", "天气工作流" in result.message, f"message={result.message}")
    check("bridge execute — result_refs 非空", len(result.result_refs) == 1, f"count={len(result.result_refs)}")
    check("bridge execute — result_kind=json", result.result_refs[0].result_kind.value == "json" if hasattr(result.result_refs[0].result_kind, 'value') else str(result.result_refs[0].result_kind) == "json")
    check("bridge execute — result_dto workflow_entry_name", result.result_dto.get("workflow_entry_name") == "bridge-e2e-test", f"entry={result.result_dto.get('workflow_entry_name')}")
    check("bridge execute — events 非空", len(result.events) == 2, f"events={len(result.events)}")
    check("bridge execute — diagnostics 非空", len(result.diagnostics) > 0, f"diagnostics count={len(result.diagnostics)}")


# ============================================================
# 运行所有测试
# ============================================================
if __name__ == "__main__":
    print("\n" + "="*60)
    print("  端到端业务回归验证")
    print("="*60)

    tests = [
        test_workflow_engine_dag,
        test_weather_workflow_e2e,
        test_weather_point_upstream_consumption,
        test_workflow_dispatch,
        test_routes,
        test_config_consistency,
        test_weather_bridge_e2e,
    ]

    for test in tests:
        try:
            test()
        except Exception as exc:
            check(f"{test.__name__} — 异常", False, f"{exc}")
            traceback.print_exc()

    # 汇总
    total = len(_results)
    passed = sum(1 for _, ok, _ in _results if ok)
    failed = sum(1 for _, ok, _ in _results if not ok)

    print(f"\n{'='*60}")
    print(f"  汇总: {passed}/{total} 通过, {failed} 失败")
    print(f"{'='*60}")

    if failed > 0:
        print("\n失败项:")
        for name, ok, detail in _results:
            if not ok:
                print(f"  {FAIL} {name} — {detail}")

    sys.exit(1 if failed > 0 else 0)
