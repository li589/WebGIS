"""GLDAS online seed: node template + graph compile attachability."""

from __future__ import annotations

import unittest


class TestGldasOnlineSeedCompile(unittest.TestCase):
    def test_seed_compiles_with_gldas_download_node(self) -> None:
        from app.services.node_template_registry import get_node_template
        from app.services.workflow_definition_service import get_definition
        from app.services.workflow_graph_compiler import (
            compile_litegraph_to_workflow_definition,
        )

        tmpl = get_node_template("download/gldas_download")
        self.assertIsNotNone(tmpl)
        assert tmpl is not None
        self.assertEqual(tmpl.get("node_class"), "gldas_download")

        defn = get_definition("omega_avg_daily_gldas_online")
        self.assertIsNotNone(defn)
        assert defn is not None
        types = [n.get("type") for n in defn.get("nodes") or []]
        self.assertIn("download/gldas_download", types)
        self.assertIn("module/omega_avg_daily", types)

        compiled = compile_litegraph_to_workflow_definition(
            workflow_id="omega_avg_daily_gldas_online",
            name=defn.get("name"),
            description=defn.get("description"),
            nodes=defn.get("nodes", []),
            links=defn.get("links", []),
        )
        module_names = [
            (n.get("params") or {}).get("module_name")
            for n in compiled.get("nodes") or []
        ]
        self.assertIn("gldas_download", module_names)
        self.assertIn("omega_avg_daily", module_names)
        edges = compiled.get("edges") or []
        # 编译器归一化（_normalize_python_edges）：指向 datasource_selection /
        # daily_mat_sources / time_range / bbox / region 的 fan-in 边会被有意丢弃，
        # 数据源改由 request.datasource_selection 绑定注入。故此处不要求 n1→n7 边存在，
        # 只验证存活边不会命中被刮取的 fan-in 端口（防止未来回归）。
        scraped_fan_ins = {"datasource_selection", "daily_mat_sources", "time_range", "bbox", "region"}
        self.assertTrue(
            all(e.get("to_port") not in scraped_fan_ins for e in edges),
            msg=f"compiled edges must not target scraped fan-in ports, got {edges}",
        )


if __name__ == "__main__":
    unittest.main()
