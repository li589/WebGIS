"""种子图 disabled 节点不得作为输出源（编译器回归守护）。

背景（2026-08-20 FY3F 支路引入时暴露）：编译器输出推导按 reversed 扫描
第一个带 manifest 端口的节点，未跳过 ``enabled=false`` 的节点。
omega_sf_fenkuai_fy_online 尾部追加默认关闭的 FY3F 下载/转换节点后，
outputs[0].source 曾错误指向 disabled 节点（n14），触发
``workflow_definition.outputs[0].source references unknown enabled node``。

运行方式（仓库根执行）::

    Env/Python312/python.exe -m pytest Test/backend/test_seed_disabled_output_source.py -q
"""

from __future__ import annotations

import os

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:6379/15")

from app.services.workflow_definition_service import (  # noqa: E402
    _ensure_dirs,
    _sync_system_seeds,
    get_definition,
)
from app.services.workflow_graph_compiler import (  # noqa: E402
    compile_litegraph_to_workflow_definition,
)


def _compile(seed_name: str) -> dict:
    defn = get_definition(seed_name)
    assert defn is not None, f"{seed_name} seed missing"
    return compile_litegraph_to_workflow_definition(
        workflow_id=seed_name,
        name=defn.get("name"),
        description=defn.get("description"),
        nodes=defn.get("nodes", []),
        links=defn.get("links", []),
    )


def _enabled_node_ids(compiled: dict) -> set[str]:
    return {
        n["node_id"]
        for n in compiled.get("nodes") or []
        if n.get("enabled") is not False
    }


def test_fy_online_seed_output_source_references_enabled_node() -> None:
    """FY 在线种子（尾部含默认关闭的 FY3F 支路）输出源必须指向启用节点。"""
    _ensure_dirs()
    _sync_system_seeds()
    compiled = _compile("omega_sf_fenkuai_fy_online")
    outputs = compiled.get("outputs") or []
    assert outputs, "outputs 不应为空"
    enabled = _enabled_node_ids(compiled)
    for out in outputs:
        source = str(out.get("source") or "")
        assert source.startswith("node:"), f"异常 source: {source}"
        nid = source.split(".")[0].removeprefix("node:")
        assert nid in enabled, (
            f"outputs 引用了 disabled 节点 {nid}（enabled={sorted(enabled)}）"
        )


def test_disabled_tail_node_never_selected_as_output_source() -> None:
    """合成图：尾部 disabled manifest 节点不得被选为输出源。"""
    nodes = [
        {
            "id": 1,
            "type": "module/omega_sf_fenkuai",
            "pos": [0, 0],
            "properties": {"module_name": "omega_sf_fenkuai"},
        },
        {
            "id": 2,
            "type": "download/fy_download",
            "pos": [0, 100],
            "properties": {
                "enabled": False,
                "satellite": "FY3F",
                "start_date": "20250101",
                "end_date": "20250101",
            },
        },
    ]
    links = [{"0": 1, "1": 2, "2": 0, "3": 1, "4": 0, "5": "value:string"}]
    compiled = compile_litegraph_to_workflow_definition(
        workflow_id="synthetic-disabled-tail",
        name="synthetic",
        description="synthetic",
        nodes=nodes,
        links=links,
    )
    outputs = compiled.get("outputs") or []
    assert outputs, "outputs 不应为空"
    enabled = _enabled_node_ids(compiled)
    for out in outputs:
        source = str(out.get("source") or "")
        nid = source.split(".")[0].removeprefix("node:")
        assert nid in enabled, f"输出来源指向 disabled 节点: {nid}"
    assert "n2" not in enabled, "n2 应为 disabled"
