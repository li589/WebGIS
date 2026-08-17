"""Compile smoke for ALL system workflow seeds.

Guards against seed node-type drift (e.g. FY seeds using unregistered
``remote_fetch`` / ``module/fy_*`` types). Extends the stub_v1 whitelist
approach to full coverage of ``workflow_seeds/system/*.json``.

Engine routing contract:
- ``common`` / ``python_provider`` / ``weather`` seeds must compile through
  ``compile_litegraph_to_workflow_definition``.
- ``gee`` seeds bypass the LiteGraph compiler entirely: runtime dispatch
  (``workflow_timer_service._build_submit_payload``) injects a
  ``GeeWorkflowRequest`` carrying the raw graph. Compile-ability is NOT part
  of their contract; ``gee_request`` injection IS.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.workflow_graph_compiler import (
    WorkflowGraphCompileError,
    compile_litegraph_to_workflow_definition,
)

_SEED_DIR = (
    Path(__file__).resolve().parents[2]
    / "Code"
    / "backend"
    / "workflow_seeds"
    / "system"
)

_ALL_SEEDS = tuple(sorted(p.stem for p in _SEED_DIR.glob("*.json")))
_COMPILABLE_ENGINES = frozenset({"common", "python_provider", "weather"})


def test_system_seeds_present() -> None:
    assert len(_ALL_SEEDS) >= 40, f"expected >=40 system seeds, got {len(_ALL_SEEDS)}"


def _seed_engine(data: dict) -> str:
    return str((data.get("_meta") or {}).get("engine") or "python_provider")


@pytest.mark.parametrize("workflow_id", _ALL_SEEDS)
def test_system_seed_compiles(workflow_id: str) -> None:
    path = _SEED_DIR / f"{workflow_id}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    engine = _seed_engine(data)
    if engine not in _COMPILABLE_ENGINES:
        pytest.skip(f"engine={engine} seeds bypass the LiteGraph compiler")
    try:
        compiled = compile_litegraph_to_workflow_definition(
            workflow_id=workflow_id,
            name=data.get("name"),
            description=data.get("description"),
            nodes=data.get("nodes"),
            links=data.get("links"),
            allow_engines=_COMPILABLE_ENGINES,
        )
    except WorkflowGraphCompileError as exc:
        pytest.fail(f"{workflow_id} compile failed: {exc}")
    assert compiled["metadata"]["engine"], workflow_id
    assert len(compiled["nodes"]) >= 1, workflow_id


@pytest.mark.parametrize("workflow_id", _ALL_SEEDS)
def test_system_seed_runtime_engine_contract(workflow_id: str) -> None:
    """Every seed must inject the engine request matching its ``_meta.engine``."""
    from app.services.workflow_timer_service import _build_submit_payload

    data = json.loads((_SEED_DIR / f"{workflow_id}.json").read_text(encoding="utf-8"))
    engine = _seed_engine(data)
    if engine not in {"python_provider", "common", "weather", "gee"}:
        pytest.skip(f"engine={engine} has no submit-time contract")
    with patch(
        "app.services.workflow_definition_service.get_definition",
        return_value=data,
    ):
        payload = _build_submit_payload(workflow_id, {})
    if engine == "gee":
        assert payload.gee_request is not None, workflow_id
        assert payload.gee_request.workflow_id == workflow_id
        graph = payload.gee_request.workflow or {}
        assert len(graph.get("nodes") or []) >= 1, workflow_id
        return
    if engine == "weather":
        assert payload.weather_request is not None, workflow_id
        return
    assert payload.algorithm_request is not None, workflow_id
    assert payload.algorithm_request.workflow_name == workflow_id


def test_fy_seeds_use_registered_types() -> None:
    """FY 在线/NAS 链路必须用注册表规范 type（P0-1 回归守卫）。

    2026-08-18 冗余清理：fy_tb_nas_read / fy_tb_nsmc_online 已移除
    （fy_tb_online_read 的 auto NSMC→NAS 回退覆盖两者），此处仅守卫现存种子。
    """
    for name in ("fy_tb_online_read", "fy_tb_local_read"):
        data = json.loads((_SEED_DIR / f"{name}.json").read_text(encoding="utf-8"))
        for node in data.get("nodes") or []:
            assert not str(node.get("type") or "").startswith("module/fy_"), (
                f"{name} node {node.get('id')} uses legacy type {node.get('type')}"
            )


def test_ssh_sync_template_contract() -> None:
    """ssh_sync 模板与实现对齐：server_type 允许自定义 profile id；不暴露幽灵参数。"""
    from app.services.node_template_registry import get_node_template

    tpl = get_node_template("download/ssh_sync")
    params = {p["key"]: p for p in tpl.get("params") or []}
    server_type = params["server_type"]
    assert server_type["options"][:3] == ["hpc", "win11", "nas"]
    assert server_type.get("allow_custom") is True
    # max_depth 在 sync_dataset 中无实现，不得渲染给用户（幽灵参数回归守卫）
    assert "max_depth" not in params
    # 模板暴露的其余参数均可被 SshSyncModule.default_params 消费
    module_consumable = {
        "server_type",
        "host",
        "port",
        "username",
        "password",
        "key_filename",
        "ssh_alias",
        "filebrowser_url",
        "proxy_command",
        "remote_path",
        "local_path",
        "start_date",
        "end_date",
        "date_start",
        "date_end",
        "file_filter",
        "dry_run",
    }
    assert set(params) <= module_consumable, sorted(set(params) - module_consumable)
