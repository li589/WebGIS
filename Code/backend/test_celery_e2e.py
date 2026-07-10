"""端到端验证脚本：覆盖 runtime/status、runtime/config、workflow 提交、
事件轮询、结果引用、cache/redis 观测等全链路。

使用方式：
    # 前置：后端 FastAPI 已启动（python -m app.main 或 run_start.bat）
    python test_celery_e2e.py [--base-url http://127.0.0.1:8000] [--timeout 60]

退出码：
    0 = 全部通过
    1 = 有失败项
"""
from __future__ import annotations

import argparse
import sys
import time
from typing import Any

import requests

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
TERMINAL_STATUSES = {"succeeded", "failed", "cancelled", "retry_pending"}


class E2EReport:
    def __init__(self) -> None:
        self.passed: list[str] = []
        self.failed: list[tuple[str, str]] = []
        self.skipped: list[tuple[str, str]] = []

    def ok(self, name: str) -> None:
        self.passed.append(name)
        print(f"  [PASS] {name}")

    def fail(self, name: str, reason: str) -> None:
        self.failed.append((name, reason))
        print(f"  [FAIL] {name}: {reason}")

    def skip(self, name: str, reason: str) -> None:
        self.skipped.append((name, reason))
        print(f"  [SKIP] {name}: {reason}")

    def summary(self) -> int:
        print("\n" + "=" * 60)
        print(f"通过: {len(self.passed)}  失败: {len(self.failed)}  跳过: {len(self.skipped)}")
        if self.failed:
            print("失败项:")
            for name, reason in self.failed:
                print(f"  - {name}: {reason}")
        print("=" * 60)
        return 0 if not self.failed else 1


def _request(method: str, url: str, **kwargs: Any) -> requests.Response:
    kwargs.setdefault("timeout", 10)
    return requests.request(method, url, **kwargs)


def test_health(base_url: str, report: E2EReport) -> None:
    print("\n[1] 健康检查 /health")
    try:
        resp = _request("GET", f"{base_url}/health")
        if resp.status_code == 200:
            report.ok("health 200")
        else:
            report.fail("health", f"status={resp.status_code}")
    except Exception as exc:
        report.fail("health", str(exc))


def test_runtime_status(base_url: str, report: E2EReport) -> dict[str, Any] | None:
    print("\n[2] 运行时状态 /runtime/status")
    name = "runtime_status"
    try:
        resp = _request("GET", f"{base_url}/runtime/status")
        if resp.status_code != 200:
            report.fail(name, f"status={resp.status_code} body={resp.text[:200]}")
            return None
        data = resp.json()
        overall = data.get("overall_health")
        active = data.get("active_run_count")
        services = data.get("services", [])
        print(f"   overall_health={overall}  active_run_count={active}  services={len(services)}")
        for svc in services:
            svc_name = svc.get("service_name")
            health = svc.get("health")
            msg = svc.get("message", "")
            print(f"     - {svc_name}: {health}  ({msg[:60]})")
        # 验证 redis_cache 服务条目存在（P1-5 新增）
        svc_names = [s.get("service_name") for s in services]
        if "redis_cache" in svc_names:
            report.ok("redis_cache service present")
        else:
            report.skip("redis_cache service present", "redis_cache 条目未出现（可能 Redis 未启用）")
        report.ok(name)
        return data
    except Exception as exc:
        report.fail(name, str(exc))
        return None


def test_runtime_config_get(base_url: str, report: E2EReport) -> dict[str, Any] | None:
    print("\n[3] 运行时配置读取 /runtime/config")
    name = "runtime_config_get"
    try:
        resp = _request("GET", f"{base_url}/runtime/config")
        if resp.status_code != 200:
            report.fail(name, f"status={resp.status_code}")
            return None
        data = resp.json()
        scopes = list(data.keys())
        print(f"   config scopes: {scopes}")
        backend_cfg = data.get("backend", {})
        if "max_active_runs" in backend_cfg:
            print(f"   max_active_runs={backend_cfg.get('max_active_runs')}")
        report.ok(name)
        return data
    except Exception as exc:
        report.fail(name, str(exc))
        return None


def test_runtime_config_patch(base_url: str, report: E2EReport) -> None:
    print("\n[4] 运行时配置更新 PATCH /runtime/config")
    name = "runtime_config_patch"
    payload = {
        "items": [
            {
                "scope": "frontend",
                "key": "ui_density",
                "value": "compact",
                "description": "E2E 验证脚本测试写入",
            }
        ]
    }
    try:
        resp = _request("PATCH", f"{base_url}/runtime/config", json=payload)
        if resp.status_code != 200:
            report.fail(name, f"status={resp.status_code} body={resp.text[:200]}")
            return
        data = resp.json()
        if data.get("accepted") and data.get("applied_count", 0) >= 1:
            report.ok(name)
        else:
            report.fail(name, f"未接受: {data}")
    except Exception as exc:
        report.fail(name, str(exc))


def test_workflow_submit_and_poll(
    base_url: str,
    report: E2EReport,
    *,
    timeout: int = 60,
    command_label: str = "E2E 测试任务",
) -> str | None:
    print("\n[5] 工作流提交 + 状态轮询")
    name = "workflow_submit_poll"
    payload = {
        "command_type": "analysis",
        "command_label": command_label,
        "priority": "normal",
        "resource_profile": "standard",
        "parameters": {
            "test_mode": True,
            "description": "E2E 端到端验证",
        },
        "requested_outputs": ["json"],
    }
    try:
        resp = _request("POST", f"{base_url}/workflow-runs", json=payload)
        if resp.status_code != 202:
            report.fail(name, f"submit status={resp.status_code} body={resp.text[:200]}")
            return None
        accepted = resp.json()
        run_id = accepted["run_id"]
        status_url = accepted["status_url"]
        print(f"   提交成功 run_id={run_id}")
    except Exception as exc:
        report.fail(name, str(exc))
        return None

    # 轮询
    poll_interval = 2
    elapsed = 0
    final_status: str | None = None
    final_data: dict[str, Any] = {}
    while elapsed < timeout:
        time.sleep(poll_interval)
        elapsed += poll_interval
        try:
            sr = _request("GET", f"{base_url}{status_url}")
            if sr.status_code != 200:
                print(f"   [{elapsed}s] 查询失败 status={sr.status_code}")
                continue
            final_data = sr.json()
            final_status = final_data.get("status")
            progress = final_data.get("progress")
            print(f"   [{elapsed}s] status={final_status} progress={progress}")
            if final_status in TERMINAL_STATUSES:
                break
        except Exception as exc:
            print(f"   [{elapsed}s] 查询异常: {exc}")

    if final_status is None:
        report.fail(name, f"{timeout}s 内未进入终态")
        return run_id

    if final_status == "succeeded":
        result_refs = final_data.get("result_refs", [])
        diagnostics = final_data.get("diagnostics", [])
        print(f"   result_refs={len(result_refs)}  diagnostics={len(diagnostics)}")
        report.ok(name)
    else:
        report.fail(name, f"最终状态={final_status}")

    return run_id


def test_workflow_events(base_url: str, run_id: str, report: E2EReport) -> None:
    print("\n[6] 工作流事件 /workflow-runs/{id}/events")
    name = "workflow_events"
    if not run_id:
        report.skip(name, "无 run_id")
        return
    try:
        resp = _request("GET", f"{base_url}/workflow-runs/{run_id}/events")
        if resp.status_code != 200:
            report.fail(name, f"status={resp.status_code}")
            return
        data = resp.json()
        events = data.get("events", [])
        print(f"   事件数: {len(events)}")
        for ev in events[:5]:
            print(f"     - [{ev.get('channel')}] {ev.get('message', '')[:50]}")
        report.ok(name)
    except Exception as exc:
        report.fail(name, str(exc))


def test_workflow_view(base_url: str, run_id: str, report: E2EReport) -> None:
    print("\n[7] 工作流结果视图 /workflow-runs/{id}/view")
    name = "workflow_view"
    if not run_id:
        report.skip(name, "无 run_id")
        return
    try:
        resp = _request("GET", f"{base_url}/workflow-runs/{run_id}/view")
        if resp.status_code == 404:
            report.skip(name, "结果视图尚未生成")
            return
        if resp.status_code != 200:
            report.fail(name, f"status={resp.status_code}")
            return
        data = resp.json()
        panels = data.get("panels", [])
        print(f"   面板数: {len(panels)}")
        report.ok(name)
    except Exception as exc:
        report.fail(name, str(exc))


def test_redis_cache_stats(base_url: str, report: E2EReport) -> None:
    print("\n[8] Redis 缓存统计（通过 /runtime/status details 校验）")
    name = "redis_cache_stats"
    try:
        resp = _request("GET", f"{base_url}/runtime/status")
        if resp.status_code != 200:
            report.fail(name, f"status={resp.status_code}")
            return
        services = resp.json().get("services", [])
        redis_svc = next((s for s in services if s.get("service_name") == "redis_cache"), None)
        if redis_svc is None:
            report.skip(name, "redis_cache 服务条目不存在")
            return
        details = redis_svc.get("details", {})
        available = details.get("available")
        print(f"   available={available}  db_size={details.get('db_size')}  weather_keys={details.get('weather_cache_keys')}")
        if available:
            report.ok(name)
        else:
            report.skip(name, f"Redis 不可用: {details.get('reason') or details.get('error')}")
    except Exception as exc:
        report.fail(name, str(exc))


def test_layers_catalog(base_url: str, report: E2EReport) -> None:
    print("\n[9] 图层目录 /layers")
    name = "layers_catalog"
    try:
        # /layers 首次调用需导入 dataset_config + 并行 readiness 检查，
        # 已知首次响应较慢（~70s），放宽到 120s
        resp = _request("GET", f"{base_url}/layers", timeout=120)
        if resp.status_code != 200:
            report.fail(name, f"status={resp.status_code}")
            return
        data = resp.json()
        layers = data.get("items", data.get("layers", []))
        print(f"   图层数: {len(layers)}")
        report.ok(name)
    except Exception as exc:
        report.fail(name, str(exc))


def test_minio_object_store(report: E2EReport) -> None:
    print("\n[10] MinIO 对象存储读写联调")
    name = "minio_object_store"
    try:
        from app.services.object_store import object_store, MinioObjectStore
        from app.core.config import settings

        backend = settings.object_store_backend.lower()
        print(f"   backend={backend}  store_class={type(object_store).__name__}")
        if backend != "minio":
            report.skip(name, f"object_store_backend={backend}（非 minio）")
            return

        key = "e2e-test/minio-health-check.json"
        data = b'{"test": "minio integration", "source": "e2e"}'
        # PUT
        stored = object_store.put_bytes(
            object_key=key,
            data=data,
            content_type="application/json",
            metadata={"source": "e2e-test"},
        )
        print(f"   PUT ok: key={stored.object_key} len={stored.content_length}")
        # GET
        fetched = object_store.fetch_bytes(key)
        if fetched != data:
            report.fail(name, f"GET 数据不一致 (len={len(fetched) if fetched else 0})")
            return
        print(f"   GET ok: match=True")
        # Cleanup
        if isinstance(object_store, MinioObjectStore):
            object_store._client.remove_object(object_store._bucket, key)
            print("   CLEANUP ok")
        report.ok(name)
    except Exception as exc:
        report.fail(name, str(exc))


def main() -> int:
    parser = argparse.ArgumentParser(description="后端端到端验证脚本")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="后端 API 基址")
    parser.add_argument("--timeout", type=int, default=60, help="工作流轮询超时秒数")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    report = E2EReport()

    print("=" * 60)
    print("端到端验证脚本")
    print(f"target: {base_url}")
    print("=" * 60)

    test_health(base_url, report)
    status_data = test_runtime_status(base_url, report)
    test_runtime_config_get(base_url, report)
    test_runtime_config_patch(base_url, report)
    run_id = test_workflow_submit_and_poll(base_url, report, timeout=args.timeout)
    test_workflow_events(base_url, run_id, report) if run_id else None
    test_workflow_view(base_url, run_id, report) if run_id else None
    test_redis_cache_stats(base_url, report)
    test_layers_catalog(base_url, report)
    test_minio_object_store(report)

    return report.summary()


if __name__ == "__main__":
    sys.exit(main())
