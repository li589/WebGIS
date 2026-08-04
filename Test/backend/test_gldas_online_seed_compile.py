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
        self.assertTrue(
            any(e.get("from_node") == "n1" and e.get("to_node") == "n7" for e in edges),
            msg=f"expected n1→n7 edge, got {edges}",
        )


if __name__ == "__main__":
    unittest.main()
