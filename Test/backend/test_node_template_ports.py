from __future__ import annotations


from app.services.node_template_registry import (
    get_all_node_templates,
    get_node_template,
)


def test_parameter_nodes_exist_under_param_category() -> None:
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
        assert tpl is not None, node_type
        assert tpl is not None
        assert tpl["category"] == "参数与范围", 'tpl["category"] == "参数与范围"'


def test_remote_sensing_modules_accept_time_range_and_bbox() -> None:
    for node_type in (
        "module/smap_daily",
        "module/ndvi_daily",
        "module/fy_daily",
        "module/timeseries_bundle",
    ):
        tpl = get_node_template(node_type)
        assert tpl is not None, node_type
        assert tpl is not None
        input_types = {p["name"]: p["type"] for p in tpl["inputs"]}
        assert input_types.get("time_range") == "value:time_range", 'input_types.get("time_range") == "value:time_range"'
        assert input_types.get("bbox") == "geometry:bbox", 'input_types.get("bbox") == "geometry:bbox"'


def test_gee_clip_accepts_bbox_geometry() -> None:
    tpl = get_node_template("gee/clip")
    assert tpl is not None, 'tpl is not None'
    assert tpl is not None
    geometry = next(p for p in tpl["inputs"] if p["name"] == "geometry")
    assert geometry["type"] == "geometry:bbox", 'geometry["type"] == "geometry:bbox"'


def test_templates_count_increased_with_param_nodes() -> None:
    types = {t["type"] for t in get_all_node_templates()}
    assert "data/latlng" in types, '"data/latlng" in types'
    assert "data/map_viewport" in types, '"data/map_viewport" in types'


def test_dimension_ports_injected_for_weather_and_stats() -> None:
    for node_type in (
        "weather/tile_render",
        "weather/temperature_render",
        "stats/temporal_trend",
    ):
        tpl = get_node_template(node_type)
        assert tpl is not None, node_type
        assert tpl is not None
        names = {p["name"] for p in tpl["inputs"]}
        assert "time_range" in names, node_type
        assert "bbox" in names, node_type


def test_preprocess_gets_bbox_but_not_forced_time() -> None:
    tpl = get_node_template("preprocess/clip")
    assert tpl is not None, 'tpl is not None'
    assert tpl is not None
    names = {p["name"]: p["type"] for p in tpl["inputs"]}
    assert names.get("bbox") == "geometry:bbox", 'names.get("bbox") == "geometry:bbox"'


def test_param_nodes_not_injected_with_time_range_input() -> None:
    tpl = get_node_template("data/time_range")
    assert tpl is not None, 'tpl is not None'
    assert tpl is not None
    names = {p["name"] for p in tpl["inputs"]}
    assert "time_range" not in names, '"time_range" not in names'


def test_former_stub_nodes_are_executable_python_provider() -> None:
    """2026-08 stub enablement: preprocess/stats/fusion/viz/gis are runnable."""
    former_stubs = (
        "preprocess/reproject",
        "preprocess/resample",
        "preprocess/clip",
        "preprocess/mask",
        "stats/spatial_mean",
        "stats/temporal_trend",
        "stats/anomaly_detect",
        "stats/correlation",
        "fusion/spatial_interpolate",
        "fusion/multi_source_merge",
        "viz/report_export",
        "viz/statistics_summary",
        "gis/buffer_analysis",
        "gis/zonal_statistics",
        "gis/raster_calculator",
        "gis/vector_to_raster",
        "gis/raster_to_vector",
        "gis/reclassify",
        "gis/contour",
        "gis/slope_aspect",
        "gis/watershed",
    )
    for node_type in former_stubs:
        tpl = get_node_template(node_type)
        assert tpl is not None, node_type
        assert tpl is not None
        assert tpl.get("executable"), node_type
        assert tpl.get("engine") == "python_provider", node_type
        assert str(tpl.get("node_class") or "").strip(), node_type
