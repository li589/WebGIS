from __future__ import annotations


def test_explanation_only_instruction_blocks_data_tools(monkeypatch):
    from app.services.agent import server_tools_runtime as runtime

    called = False

    def fake_stats(*args, **kwargs):
        nonlocal called
        called = True
        return {"ok": True, "mean": 0.2}

    monkeypatch.setattr(runtime, "_get_layer_statistics", fake_stats)
    out = runtime.execute_server_tool(
        "get_layer_statistics",
        {"catalog_id": "imported-sm"},
        user_message="现在换一个任务，只解释 VOD，不要统计。",
    )

    assert out["ok"] is False
    assert out["error_code"] == "blocked_by_current_instruction"
    assert called is False


def test_point_page_time_is_not_claimed_as_actual_time(monkeypatch):
    from app.services.agent import server_tools_runtime as runtime

    monkeypatch.setattr(runtime, "_filter_ids", lambda ids, cred: list(ids))
    monkeypatch.setattr(
        runtime,
        "_sample_one_layer",
        lambda *args, **kwargs: {
            "ok": True,
            "catalog_id": "imported-cmfd",
            "value": 2.0,
            "actual_time": None,
        },
    )

    out = runtime._sample_layer_point(
        {"catalog_id": "imported-cmfd", "lng": 116.4, "lat": 39.9},
        cred=None,
        client_context={"timeline": {"date": "2025-07-31"}},
    )

    assert out["ok"] is True
    assert out["time_source"] == "page"
    assert out["page_time"] == "2025-07-31"
    assert out["time_verified"] is False
    assert "页面时间轴日期不是数据实际时间" in out["time_warning"]
    assert out["samples"][0]["time_verified"] is False


def test_point_explicit_time_mismatch_does_not_return_value(monkeypatch):
    from app.services.agent import server_tools_runtime as runtime

    monkeypatch.setattr(runtime, "_filter_ids", lambda ids, cred: list(ids))
    monkeypatch.setattr(
        runtime,
        "_sample_one_layer",
        lambda *args, **kwargs: {
            "ok": True,
            "catalog_id": "imported-cmfd",
            "value": 2.0,
            "actual_time": "20020101",
        },
    )

    out = runtime._sample_layer_point(
        {
            "catalog_id": "imported-cmfd",
            "lng": 116.4,
            "lat": 39.9,
            "time": "2025-07-31",
        },
        cred=None,
    )

    assert out["ok"] is False
    assert out["samples"][0]["error_code"] == "actual_time_mismatch"
    assert "value" not in out["samples"][0]


def test_unresolved_region_is_explicitly_locked(monkeypatch):
    from app.services.agent import region
    from app.services.agent import server_tools_runtime as runtime

    monkeypatch.setattr(runtime, "_filter_ids", lambda ids, cred: list(ids))
    monkeypatch.setattr(region, "resolve_region", lambda name: None)

    out = runtime._get_layer_statistics(
        {"catalog_id": "imported-sm", "region": "甲壳虫省", "time": "2025-07-15"},
        cred=None,
        user_message="统计甲壳虫省2025年7月15日的土壤水分均值",
    )

    assert out["ok"] is False
    assert out["error_code"] == "region_not_resolved"
    assert out["scope_locked"] is True
    assert out["must_not_fallback_to_full_extent"] is True
    assert out["requested_region"] == "甲壳虫省"


def test_explicit_no_substitute_requires_an_exact_single_day():
    from app.services.agent.server_tools_runtime import _requires_exact_single_day

    assert _requires_exact_single_day(
        "如果这一天取不到，直接说无法完成，不要用其他日期或全国均值替代。",
        "20250715",
        "20250715",
    )
    assert not _requires_exact_single_day(
        "查询 2025 年 7 月 15 日北京土壤水分。",
        "20250715",
        "20250715",
    )
    assert not _requires_exact_single_day("不要替代。", None, "20250715")


def test_statistics_does_not_return_covering_block_when_substitute_is_forbidden(
    monkeypatch,
):
    from app.services.agent import server_tools_runtime as runtime

    class FakeSpec:
        default_time = "20250701_20250731"
        time_list = ["20250701_20250731"]
        source_reader = "geotiff"

        def resolve_time_key(self, value, prefer_finest=False):
            return "20250701_20250731"

    monkeypatch.setattr(runtime, "_filter_ids", lambda ids, cred: list(ids))
    monkeypatch.setattr(runtime, "_cross_source_guard", lambda *a, **k: None)
    monkeypatch.setattr(
        runtime,
        "_ensure_ondemand_frame",
        lambda *a, **k: {"attempted": True, "ok": False, "reason": "fetch_failed"},
    )
    monkeypatch.setattr(
        "app.services.overlay_registry.get_overlay_spec", lambda layer_id: FakeSpec()
    )

    out = runtime._get_layer_statistics(
        {"catalog_id": "imported-sm", "time": "2025-07-15"},
        cred=None,
        user_message=(
            "查询2025年7月15日北京土壤水分；取不到就直接说无法完成，"
            "不要用其他日期或全国均值替代。"
        ),
    )

    assert out["ok"] is False
    assert out["strict_time_match"] is True
    assert out["must_not_use_block_or_nearby_date"] is True
    assert "mean" not in out
    assert "整月、多日合成" in out["user_facing"]
