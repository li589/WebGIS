from __future__ import annotations

import unittest

from app.services.node_template_registry import (
    get_all_node_templates,
    get_node_template,
)


class NodeTemplatePortTests(unittest.TestCase):
    def test_parameter_nodes_exist_under_param_category(self) -> None:
        for node_type in (
            "data/time_range",
            "data/bbox",
            "data/map_viewport",
            "data/number",
            "data/string",
            "data/boolean",
            "data/latlng",
        ):
            tpl = get_node_template(node_type)
            self.assertIsNotNone(tpl, node_type)
            assert tpl is not None
            self.assertEqual(tpl["category"], "参数与范围")

    def test_remote_sensing_modules_accept_time_range_and_bbox(self) -> None:
        for node_type in (
            "module/smap_daily",
            "module/ndvi_daily",
            "module/fy_daily",
            "module/timeseries_bundle",
        ):
            tpl = get_node_template(node_type)
            self.assertIsNotNone(tpl, node_type)
            assert tpl is not None
            input_types = {p["name"]: p["type"] for p in tpl["inputs"]}
            self.assertEqual(input_types.get("time_range"), "value:time_range")
            self.assertEqual(input_types.get("bbox"), "geometry:bbox")

    def test_gee_clip_accepts_bbox_geometry(self) -> None:
        tpl = get_node_template("gee/clip")
        self.assertIsNotNone(tpl)
        assert tpl is not None
        geometry = next(p for p in tpl["inputs"] if p["name"] == "geometry")
        self.assertEqual(geometry["type"], "geometry:bbox")

    def test_templates_count_increased_with_param_nodes(self) -> None:
        types = {t["type"] for t in get_all_node_templates()}
        self.assertIn("data/latlng", types)
        self.assertIn("data/map_viewport", types)

    def test_dimension_ports_injected_for_weather_and_stats(self) -> None:
        for node_type in (
            "weather/tile_render",
            "weather/temperature_render",
            "stats/temporal_trend",
        ):
            tpl = get_node_template(node_type)
            self.assertIsNotNone(tpl, node_type)
            assert tpl is not None
            names = {p["name"] for p in tpl["inputs"]}
            self.assertIn("time_range", names, node_type)
            self.assertIn("bbox", names, node_type)

    def test_preprocess_gets_bbox_but_not_forced_time(self) -> None:
        tpl = get_node_template("preprocess/clip")
        self.assertIsNotNone(tpl)
        assert tpl is not None
        names = {p["name"]: p["type"] for p in tpl["inputs"]}
        self.assertEqual(names.get("bbox"), "geometry:bbox")

    def test_param_nodes_not_injected_with_time_range_input(self) -> None:
        tpl = get_node_template("data/time_range")
        self.assertIsNotNone(tpl)
        assert tpl is not None
        names = {p["name"] for p in tpl["inputs"]}
        self.assertNotIn("time_range", names)


if __name__ == "__main__":
    unittest.main()
