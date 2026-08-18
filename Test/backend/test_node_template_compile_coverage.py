"""N3: Compile coverage test — every registered node template must compile.

Iterates all templates in node_template_registry and compiles each as a
single-node minimal graph through workflow_graph_compiler. This exposes
templates that are registered but broken ("注册但坏"不可见).

Engine routing:
  - common / python_provider → compiled with default allow_engines
  - weather → compiled alone with allow_engines={"weather"}
  - gee → compiled alone with allow_engines={"gee"}
"""

from __future__ import annotations

import pytest

from app.services.node_template_registry import (
    get_all_node_templates,
    get_node_template,
    resolve_node_type,
)
from app.services.workflow_graph_compiler import (
    WorkflowGraphCompileError,
    compile_litegraph_to_workflow_definition,
)


def _classify_engine(engine: str) -> str:
    if engine == "weather":
        return "weather"
    if engine == "gee":
        return "gee"
    return "mixed"  # common + python_provider can mix


def _compile_single_node(template: dict) -> dict:
    """Compile a single-node graph from a template, returning the definition."""
    node_type = template["type"]
    engine = template.get("engine", "common")

    if engine == "weather":
        allow = frozenset({"weather"})
    elif engine == "gee":
        allow = frozenset({"gee"})
    else:
        allow = frozenset({"common", "python_provider", "weather"})

    return compile_litegraph_to_workflow_definition(
        workflow_id=f"compile_test_{node_type.replace('/', '_')}",
        name=f"Compile test: {node_type}",
        nodes=[
            {
                "id": 1,
                "type": node_type,
                "properties": {},
            }
        ],
        links=[],
        allow_engines=allow,
    )


def test_all_templates_compile():
    """Every registered template must compile as a single-node graph."""
    templates = get_all_node_templates()
    assert len(templates) > 50, f"Expected 50+ templates, got {len(templates)}"

    failures: list[str] = []

    for tmpl in templates:
        node_type = tmpl["type"]
        engine = tmpl.get("engine", "common")
        try:
            definition = _compile_single_node(tmpl)
        except WorkflowGraphCompileError as exc:
            failures.append(f"  {node_type} (engine={engine}): {exc}")
            continue
        except Exception as exc:  # noqa: BLE001
            failures.append(f"  {node_type} (engine={engine}): {type(exc).__name__}: {exc}")
            continue

        # Verify the compiled definition has at least one node
        nodes = definition.get("nodes", [])
        if not nodes:
            failures.append(
                f"  {node_type} (engine={engine}): compiled to 0 nodes"
            )

    if failures:
        pytest.fail(
            f"{len(failures)} template(s) failed compilation:\n"
            + "\n".join(failures)
        )


def test_mixed_engine_templates_compile():
    """common + python_provider templates compile under default allow_engines."""
    templates = get_all_node_templates()
    mixed = [
        t for t in templates
        if t.get("engine", "common") in ("common", "python_provider")
    ]
    assert len(mixed) > 20, f"Expected 20+ mixed-engine templates, got {len(mixed)}"

    for tmpl in mixed:
        node_type = tmpl["type"]
        try:
            definition = compile_litegraph_to_workflow_definition(
                workflow_id=f"mixed_test_{node_type.replace('/', '_')}",
                name=f"Mixed test: {node_type}",
                nodes=[{"id": 1, "type": node_type, "properties": {}}],
                links=[],
                allow_engines=frozenset({"common", "python_provider"}),
            )
            nodes = definition.get("nodes", [])
            assert nodes, f"{node_type}: compiled to 0 nodes"
        except (WorkflowGraphCompileError, AssertionError):
            raise
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"{node_type}: {type(exc).__name__}: {exc}")


def test_weather_templates_compile_alone():
    """Weather-engine templates compile under allow_engines={'weather'}."""
    templates = get_all_node_templates()
    weather = [t for t in templates if t.get("engine") == "weather"]
    assert len(weather) >= 10, f"Expected 10+ weather templates, got {len(weather)}"

    for tmpl in weather:
        node_type = tmpl["type"]
        try:
            definition = compile_litegraph_to_workflow_definition(
                workflow_id=f"weather_test_{node_type.replace('/', '_')}",
                name=f"Weather test: {node_type}",
                nodes=[{"id": 1, "type": node_type, "properties": {}}],
                links=[],
                allow_engines=frozenset({"weather"}),
            )
            nodes = definition.get("nodes", [])
            assert nodes, f"{node_type}: compiled to 0 nodes"
        except (WorkflowGraphCompileError, AssertionError):
            raise
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"{node_type}: {type(exc).__name__}: {exc}")


def test_gee_templates_compile_alone():
    """GEE-engine templates compile under allow_engines={'gee'}."""
    templates = get_all_node_templates()
    gee = [t for t in templates if t.get("engine") == "gee"]
    if not gee:
        pytest.skip("No GEE templates registered")

    for tmpl in gee:
        node_type = tmpl["type"]
        try:
            definition = compile_litegraph_to_workflow_definition(
                workflow_id=f"gee_test_{node_type.replace('/', '_')}",
                name=f"GEE test: {node_type}",
                nodes=[{"id": 1, "type": node_type, "properties": {}}],
                links=[],
                allow_engines=frozenset({"gee"}),
            )
            nodes = definition.get("nodes", [])
            assert nodes, f"{node_type}: compiled to 0 nodes"
        except (WorkflowGraphCompileError, AssertionError):
            raise
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"{node_type}: {type(exc).__name__}: {exc}")


def test_type_aliases_resolve():
    """Legacy type aliases must resolve to canonical types."""
    aliases = {
        "algorithm/omega_avg_daily": "module/omega_avg_daily",
        "remote_fetch": "download/remote_fetch",
        "module/fy_preprocess": "download/fy_preprocess",
        "module/fy_download": "download/fy_download",
    }
    for alias, expected in aliases.items():
        resolved = resolve_node_type(alias)
        assert resolved == expected, (
            f"resolve_node_type('{alias}') returned '{resolved}', expected '{expected}'"
        )
        tmpl = get_node_template(resolved)
        assert tmpl is not None, f"Canonical type '{resolved}' not in registry"
