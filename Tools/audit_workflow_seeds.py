"""工作流种子全量审计工具（校验类辅助脚本）。

对 ``Code/backend/workflow_seeds/system/*.json`` 执行全量核查：
- 逐个 LiteGraph 编译（engine=gee 按契约跳过，标记 bypass）
- dry-validate 结构规则（empty_graph / no_module / module_name_missing）
- category 白名单与 tag 词表校验（词表真源：Docs/03-规范协议/workflow_seed_conventions.md §5）
- 节点类型 ↔ node_template_registry 双向差集
- 节点类型多重集哈希检测重复组
- 交叉引用：layer_descriptors.json workflow_name、.data/workflow_definitions/system 孤儿、
  workflow_state.sqlite3 workflow_timers 引用（只读）

用法（仓库根）::

    Env/Python312/python.exe Tools/audit_workflow_seeds.py [--out report.md]

退出码：存在硬失败（编译失败 / 未注册节点 / 非法 category / .data 孤儿 /
timer 引用缺失种子）时为 1，否则 0；tag 词表漂移仅告警。
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "Code" / "backend"
SEED_DIR = BACKEND_ROOT / "workflow_seeds" / "system"
ARCHIVE_DIR = BACKEND_ROOT / "workflow_seeds" / "archive"
CONVENTIONS_DOC = REPO_ROOT / "Docs" / "03-规范协议" / "workflow_seed_conventions.md"
LAYER_DESCRIPTORS = BACKEND_ROOT / "app" / "catalog_seeds" / "layer_descriptors.json"
DATA_SYSTEM_DIR = BACKEND_ROOT / ".data" / "workflow_definitions" / "system"
TIMER_DB_CANDIDATES = (
    BACKEND_ROOT / ".data" / "workflow_state" / "workflow_state.sqlite3",
    BACKEND_ROOT / ".data" / "_runtime" / "workflow_state" / "workflow_state.sqlite3",
)

sys.path.insert(0, str(BACKEND_ROOT))

from app.services.node_template_registry import (  # noqa: E402
    get_all_node_templates,
    resolve_node_type,
)
from app.services.workflow_graph_compiler import (  # noqa: E402
    WorkflowGraphCompileError,
    compile_litegraph_to_workflow_definition,
)

COMPILABLE_ENGINES = frozenset({"common", "python_provider", "weather"})
CATEGORY_WHITELIST = frozenset({"inversion", "weather", "data_access", "analysis", "demo"})

# 与 workflow_definition_router.dry_validate_graph 的 _HELPER_MODULES 保持一致
HELPER_MODULES = frozenset(
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


def load_tag_vocabulary() -> set[str]:
    """从规范文档 §5 解析 tag 词表（文档为单一真源）。"""
    text = CONVENTIONS_DOC.read_text(encoding="utf-8")
    match = re.search(r"## 5\..*?`(.*?)`.*?###", text, re.DOTALL)
    if not match:
        raise SystemExit(f"无法从 {CONVENTIONS_DOC} 解析 tag 词表")
    section = text[match.start() : match.end()]
    return set(re.findall(r"`([^`]+)`", section))


def load_layer_workflow_names() -> set[str]:
    def walk(obj: Any, found: set[str]) -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key == "workflow_name" and isinstance(value, str) and value:
                    found.add(value)
                else:
                    walk(value, found)
        elif isinstance(obj, list):
            for item in obj:
                walk(item, found)

    names: set[str] = set()
    walk(json.loads(LAYER_DESCRIPTORS.read_text(encoding="utf-8")), names)
    return names


def probe_timer_refs(seed_ids: set[str]) -> tuple[list[str], str]:
    """只读查询 workflow_timers 对种子的引用（找不到 DB 时跳过）。"""
    db_path = next((p for p in TIMER_DB_CANDIDATES if p.exists()), None)
    if db_path is None:
        return [], "workflow_state.sqlite3 未找到，跳过"
    refs: list[str] = []
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
            rows = conn.execute(
                "SELECT workflow_id FROM workflow_timers"
            ).fetchall()
        for (workflow_id,) in rows:
            wid = str(workflow_id or "")
            if wid and wid not in seed_ids:
                refs.append(wid)
    except sqlite3.Error as exc:
        return [], f"查询失败（跳过）: {exc}"
    return sorted(set(refs)), f"DB={db_path.name}"


def dry_validate_compiled(
    definition: dict[str, Any], *, weather_engine: bool
) -> list[str]:
    """复用 dry_validate_graph 的结构规则，返回 issue 描述列表。

    weather 引擎编译产物为原生 weatherengine 执行节点（node_type 即执行器），
    module/* 检查仅适用于 python/common 画布，故跳过 no_module 规则。
    """
    issues: list[str] = []
    nodes = definition.get("nodes") if isinstance(definition, dict) else None
    if not isinstance(nodes, list) or not nodes:
        return ["empty_graph"]
    if weather_engine:
        return issues

    def module_name_of(node: dict[str, Any]) -> str:
        props = node.get("properties") if isinstance(node.get("properties"), dict) else {}
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
        return ntype.split("/", 1)[-1] if "/" in ntype else ntype

    module_nodes = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        ntype = str(node.get("type") or "")
        node_type = str(node.get("node_type") or "")
        mname = module_name_of(node)
        if mname in HELPER_MODULES:
            continue
        if ntype.startswith("module/") or (
            node_type == "module" and mname not in {"", "module"}
        ):
            module_nodes.append(node)

    if not module_nodes:
        issues.append("no_module")
    for node in module_nodes:
        if not module_name_of(node):
            issues.append(f"module_name_missing:{node.get('node_id') or node.get('id')}")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=None, help="审计报告输出路径（markdown）")
    args = parser.parse_args()

    vocabulary = load_tag_vocabulary()
    layer_refs = load_layer_workflow_names()
    registry_types = {str(t["type"]) for t in get_all_node_templates()}

    seed_paths = sorted(SEED_DIR.glob("*.json"))
    rows: list[dict[str, Any]] = []
    tag_drift: dict[str, list[str]] = {}
    referenced_types: set[str] = set()
    dup_groups: dict[str, list[str]] = {}
    failures: list[str] = []

    for path in seed_paths:
        workflow_id = path.stem
        data = json.loads(path.read_text(encoding="utf-8"))
        meta = data.get("_meta") or {}
        engine = str(meta.get("engine") or "python_provider")
        category = meta.get("category")
        tags = [str(t) for t in (meta.get("tags") or [])]

        node_types = sorted(
            resolve_node_type(str(n.get("type") or ""))
            for n in (data.get("nodes") or [])
            if isinstance(n, dict)
        )
        referenced_types.update(node_types)

        for tag in tags:
            if tag not in vocabulary:
                tag_drift.setdefault(tag, []).append(workflow_id)

        unregistered = [t for t in node_types if t not in registry_types]

        compile_status = "bypass"
        dv_issues: list[str] = []
        if engine in COMPILABLE_ENGINES:
            try:
                compiled = compile_litegraph_to_workflow_definition(
                    workflow_id=workflow_id,
                    name=data.get("name"),
                    description=data.get("description"),
                    nodes=data.get("nodes"),
                    links=data.get("links"),
                    allow_engines=COMPILABLE_ENGINES,
                )
                compile_status = "ok"
                dv_issues = dry_validate_compiled(
                    compiled, weather_engine=engine == "weather"
                )
            except WorkflowGraphCompileError as exc:
                compile_status = f"FAIL: {exc}"
                failures.append(f"{workflow_id}: 编译失败 {exc}")
        if unregistered:
            failures.append(f"{workflow_id}: 未注册节点类型 {unregistered}")
        if category is not None and category not in CATEGORY_WHITELIST:
            failures.append(f"{workflow_id}: 非法 category {category!r}")
        if dv_issues:
            failures.append(f"{workflow_id}: dry-validate {dv_issues}")

        dup_key = "|".join(node_types)
        dup_groups.setdefault(dup_key, []).append(workflow_id)

        rows.append(
            {
                "id": workflow_id,
                "engine": engine,
                "category": category or "-",
                "nodes": len(data.get("nodes") or []),
                "compile": compile_status,
                "dv": ",".join(dv_issues) if dv_issues else "ok",
                "registry": ",".join(unregistered) if unregistered else "ok",
                "layer_ref": "yes" if workflow_id in layer_refs else "-",
            }
        )

    duplicates = {
        key: ids for key, ids in dup_groups.items() if len(ids) > 1
    }
    referenced_missing = sorted(t for t in referenced_types if t not in registry_types)

    orphan_paths: list[str] = []
    if DATA_SYSTEM_DIR.is_dir():
        seed_ids = {p.stem for p in seed_paths}
        for stale in sorted(DATA_SYSTEM_DIR.glob("*.json")):
            if stale.stem not in seed_ids:
                orphan_paths.append(stale.name)
    if orphan_paths:
        failures.append(f".data 孤儿副本: {orphan_paths}")

    timer_refs, timer_note = probe_timer_refs({p.stem for p in seed_paths})
    if timer_refs:
        failures.append(f"workflow_timers 引用缺失种子: {timer_refs}")

    lines: list[str] = []
    lines.append("# 工作流种子全量审计报告")
    lines.append("")
    lines.append(f"- 种子数：{len(seed_paths)}（system/）")
    if ARCHIVE_DIR.is_dir():
        lines.append(f"- 归档数：{len(list(ARCHIVE_DIR.glob('*.json')))}（archive/）")
    lines.append(f"- tag 词表：{len(vocabulary)} 项（真源 workflow_seed_conventions.md §5）")
    lines.append(f"- workflow_timers：{timer_note}")
    lines.append("")
    lines.append("## 审计明细")
    lines.append("")
    lines.append("| workflow_id | engine | category | 节点数 | 编译 | dry-validate | 注册表 | 图层引用 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for row in rows:
        lines.append(
            f"| {row['id']} | {row['engine']} | {row['category']} | {row['nodes']} "
            f"| {row['compile']} | {row['dv']} | {row['registry']} | {row['layer_ref']} |"
        )
    lines.append("")

    lines.append("## 重复组（节点类型多重集相同）")
    lines.append("")
    if duplicates:
        lines.append("| 组成员 | 共同节点类型 |")
        lines.append("|---|---|")
        for key, ids in sorted(duplicates.items()):
            lines.append(f"| {', '.join(sorted(ids))} | {key.replace('|', ' + ')} |")
    else:
        lines.append("（无）")
    lines.append("")

    lines.append("## tag 词表漂移（仅告警）")
    lines.append("")
    if tag_drift:
        for tag in sorted(tag_drift):
            lines.append(f"- `{tag}`：{len(tag_drift[tag])} 个种子使用，未登记词表")
    else:
        lines.append("（无）")
    lines.append("")

    lines.append("## 注册表差集")
    lines.append("")
    lines.append(f"- 种子引用但未注册：{referenced_missing or '无'}")
    unused = sorted(registry_types - referenced_types)
    lines.append(f"- 注册但无种子使用（{len(unused)}）：{', '.join(unused) or '无'}")
    lines.append("")

    lines.append("## .data 孤儿与 timer 引用")
    lines.append("")
    lines.append(f"- `.data/workflow_definitions/system/` 孤儿：{orphan_paths or '无'}")
    lines.append(f"- workflow_timers 引用缺失种子：{timer_refs or '无'}")
    lines.append("")
    lines.append("## 结论")
    lines.append("")
    lines.append("全部通过" if not failures else "\n".join(f"- FAIL {f}" for f in failures))

    report = "\n".join(lines) + "\n"
    print(report)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report, encoding="utf-8")
        print(f"[audit] report written to {args.out}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
