"""Tests for app.services.workflow_timer_service.

覆盖：
- cron 解析（语法 + 边界 + Asia/Shanghai 墙钟）
- 触发器配置校验 / interval clamp
- WorkflowTimerStore CRUD / claim
- tick() / emit_event() / trigger_manually()（mock submission_service）
- _build_submit_payload 按 engine 注入
"""

from __future__ import annotations

import pytest
import types
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.services.workflow_timer_service import (
    CLAIM_TTL_SECONDS,
    TIMER_TZ,
    TimerValidationError,
    WorkflowTimer,
    WorkflowTimerStore,
    _build_submit_payload,
    compute_next_fire_at,
    next_cron_time,
    parse_cron,
    resolve_date_templates,
    tick,
    emit_event,
    trigger_manually,
    validate_trigger_config,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_parse_wildcard() -> None:
    result = parse_cron("* * * * *")
    assert result["minute"] == set(range(60)), 'result["minute"] == set(range(60))'
    assert result["hour"] == set(range(24)), 'result["hour"] == set(range(24))'
    assert result["day_of_month"] == set(range(1, 32)), 'result["day_of_month"] == set(range(1, 32))'
    assert result["month"] == set(range(1, 13)), 'result["month"] == set(range(1, 13))'
    assert result["day_of_week"] == set(range(7)), 'result["day_of_week"] == set(range(7))'


def test_parse_step() -> None:
    result = parse_cron("*/15 * * * *")
    assert result["minute"] == {0, 15, 30, 45}, 'result["minute"] == {0, 15, 30, 45}'


def test_parse_list() -> None:
    result = parse_cron("0,30 * * * *")
    assert result["minute"] == {0, 30}, 'result["minute"] == {0, 30}'


def test_parse_range() -> None:
    result = parse_cron("0 9-17 * * *")
    assert result["hour"] == set(range(9, 18)), 'result["hour"] == set(range(9, 18))'


def test_parse_range_with_step() -> None:
    result = parse_cron("0 9-17/2 * * *")
    assert result["hour"] == {9, 11, 13, 15, 17}, 'result["hour"] == {9, 11, 13, 15, 17}'


def test_parse_invalid_field_count() -> None:
    with pytest.raises(TimerValidationError):
        parse_cron("* * * *")
    with pytest.raises(TimerValidationError):
        parse_cron("* * * * * *")


def test_parse_out_of_range() -> None:
    with pytest.raises(TimerValidationError):
        parse_cron("60 * * * *")
    with pytest.raises(TimerValidationError):
        parse_cron("* 24 * * *")
    with pytest.raises(TimerValidationError):
        parse_cron("* * 0 * *")


def test_parse_invalid_value() -> None:
    with pytest.raises(TimerValidationError):
        parse_cron("abc * * * *")


def test_next_cron_time_shanghai_wall_clock() -> None:
    # 0 8 * * * = 每天北京时间 08:00 = UTC 00:00（无夏令时）
    # 2026-07-21 07:30 UTC = 15:30 上海 → 下次为 7/22 08:00 上海 = 7/22 00:00 UTC
    after = datetime(2026, 7, 21, 7, 30, tzinfo=timezone.utc)
    nxt = next_cron_time("0 8 * * *", after)
    assert nxt.astimezone(timezone.utc) == datetime(2026, 7, 22, 0, 0, tzinfo=timezone.utc), 'nxt.astimezone(timezone.utc) == datetime(2026, 7, 22, 0, 0, tzinfo=timezone.utc)'
    local = nxt.astimezone(SHANGHAI)
    assert local.hour == 8, 'local.hour == 8'
    assert local.minute == 0, 'local.minute == 0'


def test_next_cron_time_same_day_shanghai() -> None:
    # 北京时间 07:30 → 当天 08:00 上海
    after = datetime(2026, 7, 21, 7, 30, tzinfo=SHANGHAI).astimezone(timezone.utc)
    nxt = next_cron_time("0 8 * * *", after)
    local = nxt.astimezone(SHANGHAI)
    assert local.day == 21, 'local.day == 21'
    assert local.hour == 8, 'local.hour == 8'


def test_next_cron_time_weekday_filter() -> None:
    # 0 8 * * 1 = 每周一 08:00 上海
    # 2026-07-21 是周二
    after = datetime(2026, 7, 21, 9, 0, tzinfo=SHANGHAI).astimezone(timezone.utc)
    nxt = next_cron_time("0 8 * * 1", after)
    local = nxt.astimezone(SHANGHAI)
    assert local.day == 27, 'local.day == 27'  # 下周一
    assert local.hour == 8, 'local.hour == 8'


def test_timer_tz_constant() -> None:
    assert str(TIMER_TZ) == "Asia/Shanghai", 'str(TIMER_TZ) == "Asia/Shanghai"'


def test_validate_cron() -> None:
    cfg = validate_trigger_config("cron", {"cron": "0 8 * * *"})
    assert cfg == {"cron": "0 8 * * *"}, 'cfg == {"cron": "0 8 * * *"}'


def test_validate_cron_invalid() -> None:
    with pytest.raises(TimerValidationError):
        validate_trigger_config("cron", {"cron": "invalid"})
    with pytest.raises(TimerValidationError):
        validate_trigger_config("cron", {})


def test_validate_interval() -> None:
    cfg = validate_trigger_config("interval", {"seconds": 3600})
    assert cfg == {"seconds": 3600}, 'cfg == {"seconds": 3600}'


def test_validate_interval_too_small() -> None:
    with pytest.raises(TimerValidationError):
        validate_trigger_config("interval", {"seconds": 30})
    with pytest.raises(TimerValidationError):
        validate_trigger_config("interval", {"seconds": "abc"})


def test_validate_event() -> None:
    cfg = validate_trigger_config("event", {"event_type": "data_ready"})
    assert cfg == {"event_type": "data_ready"}, 'cfg == {"event_type": "data_ready"}'


def test_validate_event_empty() -> None:
    with pytest.raises(TimerValidationError):
        validate_trigger_config("event", {"event_type": ""})


def test_validate_unknown_type() -> None:
    with pytest.raises(TimerValidationError):
        validate_trigger_config("unknown", {})


def test_compute_next_fire_at_cron() -> None:
    result = compute_next_fire_at("cron", {"cron": "0 8 * * *"}, None)
    assert result is not None, 'result is not None'
    assert "T" in result, '"T" in result'


def test_compute_next_fire_at_interval_from_last() -> None:
    now = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)
    last = datetime(2026, 7, 21, 11, 30, tzinfo=timezone.utc)
    result = compute_next_fire_at(
        "interval", {"seconds": 3600}, last, now=now
    )
    assert result == "2026-07-21T12:30:00+00:00", 'result == "2026-07-21T12:30:00+00:00"'


def test_compute_next_fire_at_interval_clamps_past() -> None:
    now = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)
    last = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)
    result = compute_next_fire_at(
        "interval", {"seconds": 3600}, last, now=now
    )
    assert result == "2026-08-05T13:00:00+00:00", 'result == "2026-08-05T13:00:00+00:00"'


def test_compute_next_fire_at_event_returns_none() -> None:
    result = compute_next_fire_at("event", {"event_type": "x"}, None)
    assert result is None, 'result is None'


def test_resolve_today_shape() -> None:
    result = resolve_date_templates("{{today}}")
    assert isinstance(result, int), 'isinstance(result, int)'
    assert len(str(result)) == 8, 'len(str(result)) == 8'


def test_resolve_nested_dict() -> None:
    result = resolve_date_templates({"start": "{{today}}", "label": "x"})
    assert isinstance(result["start"], int), 'isinstance(result["start"], int)'
    assert result["label"] == "x", 'result["label"] == "x"'


@pytest.fixture
def _workflow_timer_store_tests_env():
    ns = types.SimpleNamespace()
    ns._tmpdir = tempfile.TemporaryDirectory()
    ns.store = WorkflowTimerStore(state_dir=Path(ns._tmpdir.name))
    yield ns
    ns.store.close()
    ns._tmpdir.cleanup()


def _make_timer(timer_id: str = "timer-test1") -> WorkflowTimer:
    return WorkflowTimer(
        timer_id=timer_id,
        workflow_id="wf-1",
        name="Test Timer",
        trigger_type="cron",
        trigger_config={"cron": "0 8 * * *"},
        payload_overrides={},
        enabled=True,
        next_fire_at="2026-07-21T08:00:00+00:00",
        created_at="2026-07-21T00:00:00+00:00",
        updated_at="2026-07-21T00:00:00+00:00",
    )


def test_create_and_get_timer(_workflow_timer_store_tests_env) -> None:
    self = _workflow_timer_store_tests_env
    timer = _make_timer()
    self.store.create_timer(timer)
    loaded = self.store.get_timer("timer-test1")
    assert loaded is not None, 'loaded is not None'
    assert loaded.workflow_id == "wf-1", 'loaded.workflow_id == "wf-1"'
    assert loaded.trigger_config == {"cron": "0 8 * * *"}, 'loaded.trigger_config == {"cron": "0 8 * * *"}'
    assert loaded.enabled, 'loaded.enabled is truthy'


def test_list_timers(_workflow_timer_store_tests_env) -> None:
    self = _workflow_timer_store_tests_env
    self.store.create_timer(_make_timer("t1"))
    self.store.create_timer(_make_timer("t2"))
    all_timers = self.store.list_timers()
    assert len(all_timers) == 2, 'len(all_timers) == 2'
    filtered = self.store.list_timers(workflow_id="wf-1")
    assert len(filtered) == 2, 'len(filtered) == 2'
    filtered_none = self.store.list_timers(workflow_id="nonexistent")
    assert len(filtered_none) == 0, 'len(filtered_none) == 0'


def test_delete_timer(_workflow_timer_store_tests_env) -> None:
    self = _workflow_timer_store_tests_env
    self.store.create_timer(_make_timer())
    assert self.store.delete_timer("timer-test1"), 'self.store.delete_timer("timer-test1") is truthy'
    assert self.store.get_timer("timer-test1") is None, 'self.store.get_timer("timer-test1") is None'
    assert not self.store.delete_timer("timer-test1"), 'self.store.delete_timer("timer-test1") is falsy'


def test_update_timer_enable_disable(_workflow_timer_store_tests_env) -> None:
    self = _workflow_timer_store_tests_env
    self.store.create_timer(_make_timer())
    updated = self.store.update_timer("timer-test1", {"enabled": False})
    assert not updated.enabled, 'updated.enabled is falsy'
    assert updated.next_fire_at is None, 'updated.next_fire_at is None'
    updated = self.store.update_timer("timer-test1", {"enabled": True})
    assert updated.enabled, 'updated.enabled is truthy'
    assert updated.next_fire_at is not None, 'updated.next_fire_at is not None'


def test_update_timer_change_trigger(_workflow_timer_store_tests_env) -> None:
    self = _workflow_timer_store_tests_env
    self.store.create_timer(_make_timer())
    updated = self.store.update_timer(
        "timer-test1",
        {"trigger_type": "interval", "trigger_config": {"seconds": 7200}},
    )
    assert updated.trigger_type == "interval", 'updated.trigger_type == "interval"'
    assert updated.trigger_config == {"seconds": 7200}, 'updated.trigger_config == {"seconds": 7200}'
    assert updated.next_fire_at is not None, 'updated.next_fire_at is not None'


def test_update_timer_type_without_config_rejected(_workflow_timer_store_tests_env) -> None:
    self = _workflow_timer_store_tests_env
    self.store.create_timer(_make_timer())
    with pytest.raises(TimerValidationError):
        self.store.update_timer("timer-test1", {"trigger_type": "interval"})


def test_fetch_due_timers(_workflow_timer_store_tests_env) -> None:
    self = _workflow_timer_store_tests_env
    past_time = "2020-01-01T00:00:00+00:00"
    timer = _make_timer()
    timer.next_fire_at = past_time
    self.store.create_timer(timer)
    future_timer = _make_timer("timer-future")
    future_timer.next_fire_at = "2099-12-31T23:59:00+00:00"
    self.store.create_timer(future_timer)

    due = self.store.fetch_due_timers(datetime(2026, 7, 21, tzinfo=timezone.utc))
    assert len(due) == 1, 'len(due) == 1'
    assert due[0].timer_id == "timer-test1", 'due[0].timer_id == "timer-test1"'


def test_fetch_due_timers_excludes_event_type(_workflow_timer_store_tests_env) -> None:
    self = _workflow_timer_store_tests_env
    timer = _make_timer()
    timer.trigger_type = "event"
    timer.trigger_config = {"event_type": "data_ready"}
    timer.next_fire_at = "2020-01-01T00:00:00+00:00"
    self.store.create_timer(timer)

    due = self.store.fetch_due_timers(datetime(2026, 7, 21, tzinfo=timezone.utc))
    assert len(due) == 0, 'len(due) == 0'


def test_claim_due_timers_idempotent(_workflow_timer_store_tests_env) -> None:
    self = _workflow_timer_store_tests_env
    timer = _make_timer()
    timer.next_fire_at = "2020-01-01T00:00:00+00:00"
    self.store.create_timer(timer)
    now = datetime(2026, 7, 21, tzinfo=timezone.utc)
    claimed1, skipped1 = self.store.claim_due_timers(now)
    assert len(claimed1) == 1, 'len(claimed1) == 1'
    assert skipped1 == 0, 'skipped1 == 0'
    claimed2, skipped2 = self.store.claim_due_timers(now)
    assert len(claimed2) == 0, 'len(claimed2) == 0'
    assert skipped2 == 0, 'skipped2 == 0'  # 已不在 due 列表
    loaded = self.store.get_timer("timer-test1")
    assert str(loaded.next_fire_at).startswith("CLAIMED:"), 'str(loaded.next_fire_at).startswith("CLAIMED:") is truthy'


def test_claim_skips_when_next_fire_raced(_workflow_timer_store_tests_env) -> None:
    """fetch 后 next_fire_at 被改写 → UPDATE 乐观锁失败计入 skipped。"""
    self = _workflow_timer_store_tests_env
    timer = _make_timer()
    timer.next_fire_at = "2020-01-01T00:00:00+00:00"
    self.store.create_timer(timer)
    now = datetime(2026, 7, 21, tzinfo=timezone.utc)
    original_fetch = self.store.fetch_due_timers

    def fetch_then_race(now_arg: datetime) -> list[WorkflowTimer]:
        due = original_fetch(now_arg)
        with self.store._lock:
            self.store._conn.execute(
                "UPDATE workflow_timers SET next_fire_at = ? WHERE timer_id = ?",
                ("2020-01-01T00:00:01+00:00", "timer-test1"),
            )
        return due

    with patch.object(self.store, "fetch_due_timers", side_effect=fetch_then_race):
        claimed, skipped = self.store.claim_due_timers(now)
    assert len(claimed) == 0, 'len(claimed) == 0'
    assert skipped == 1, 'skipped == 1'


def test_reclaim_stale_claims(_workflow_timer_store_tests_env) -> None:
    self = _workflow_timer_store_tests_env
    timer = _make_timer()
    timer.next_fire_at = "CLAIMED:2020-01-01T00:00:00+00:00:deadbeef"
    timer.updated_at = "2020-01-01T00:00:00+00:00"
    self.store.create_timer(timer)
    now = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)
    reclaimed = self.store.reclaim_stale_claims(now, ttl_seconds=CLAIM_TTL_SECONDS)
    assert reclaimed == 1, 'reclaimed == 1'
    loaded = self.store.get_timer("timer-test1")
    assert loaded.next_fire_at == now.isoformat(), 'loaded.next_fire_at == now.isoformat()'
    # 新鲜 CLAIMED（updated_at=now）不应被回收
    timer2 = _make_timer("timer-fresh")
    timer2.next_fire_at = f"CLAIMED:{now.isoformat()}:abcdef12"
    timer2.updated_at = now.isoformat()
    self.store.create_timer(timer2)
    reclaimed2 = self.store.reclaim_stale_claims(now, ttl_seconds=CLAIM_TTL_SECONDS)
    assert reclaimed2 == 0, 'reclaimed2 == 0'
    assert str(self.store.get_timer("timer-fresh").next_fire_at).startswith("CLAIMED:"), 'str(self.store.get_timer("timer-fresh").next_fire_at).startswith("CLAIMED:") is truthy'


def test_find_event_timers(_workflow_timer_store_tests_env) -> None:
    self = _workflow_timer_store_tests_env
    timer = _make_timer()
    timer.trigger_type = "event"
    timer.trigger_config = {"event_type": "data_ready"}
    self.store.create_timer(timer)

    result = self.store.find_event_timers("other_event")
    assert len(result) == 0, 'len(result) == 0'
    result = self.store.find_event_timers("data_ready")
    assert len(result) == 1, 'len(result) == 1'
    assert result[0].timer_id == "timer-test1", 'result[0].timer_id == "timer-test1"'


def test_mark_fired(_workflow_timer_store_tests_env) -> None:
    self = _workflow_timer_store_tests_env
    self.store.create_timer(_make_timer())
    self.store.mark_fired(
        "timer-test1",
        run_id="run-abc",
        error=None,
        next_fire_at="2026-07-22T08:00:00+00:00",
    )
    loaded = self.store.get_timer("timer-test1")
    assert loaded.last_run_id == "run-abc", 'loaded.last_run_id == "run-abc"'
    assert loaded.last_error is None, 'loaded.last_error is None'
    assert loaded.fire_count == 1, 'loaded.fire_count == 1'
    assert loaded.next_fire_at == "2026-07-22T08:00:00+00:00", 'loaded.next_fire_at == "2026-07-22T08:00:00+00:00"'
    assert loaded.last_fired_at is not None, 'loaded.last_fired_at is not None'


def test_python_provider_injects_workflow_name() -> None:
    definition = {
        "_meta": {
            "engine": "python_provider",
            "linked_layer_id": "omega-avg-daily",
        },
        "workflow_id": "omega_avg_daily_smap_single",
        "nodes": [
            {
                "type": "module/omega_avg_daily",
                "properties": {"algorithm_params": {"tb_source": "SMAP"}},
            }
        ],
        "links": [],
    }
    with patch(
        "app.services.workflow_definition_service.get_definition",
        return_value=definition,
    ):
        payload = _build_submit_payload("omega_avg_daily_smap_single", {})
    algo = payload.algorithm_request
    if hasattr(algo, "model_dump"):
        algo = algo.model_dump()
    elif hasattr(algo, "dict"):
        algo = algo.dict()
    assert algo.get("workflow_name") == "omega_avg_daily_smap_single", 'algo.get("workflow_name") == "omega_avg_daily_smap_single"'
    assert algo.get("workflow_definition") is not None, 'algo.get("workflow_definition") is not None'
    assert algo.get("algorithm_params", {}).get("tb_source") == "SMAP", 'algo.get("algorithm_params", {}).get("tb_source") == "SMAP"'
    assert payload.layer_id == "omega-avg-daily", 'payload.layer_id == "omega-avg-daily"'


def test_weather_injects_weather_request() -> None:
    definition = {
        "_meta": {"engine": "weather", "linked_layer_id": "temperature"},
        "workflow_id": "weather_temperature_grid_demo",
        "nodes": [],
        "links": [],
    }
    with patch(
        "app.services.workflow_definition_service.get_definition",
        return_value=definition,
    ):
        payload = _build_submit_payload("weather_temperature_grid_demo", {})
    assert payload.weather_request is not None, 'payload.weather_request is not None'
    wr = payload.weather_request
    if hasattr(wr, "model_dump"):
        wr = wr.model_dump()
    assert wr.get("workflow_id") == "weather_temperature_grid_demo", 'wr.get("workflow_id") == "weather_temperature_grid_demo"'
    assert wr.get("layer_id") == "temperature", 'wr.get("layer_id") == "temperature"'


def test_gee_injects_gee_request() -> None:
    definition = {
        "_meta": {"engine": "gee"},
        "workflow_id": "gee_demo",
        "nodes": [{"id": 1, "type": "gee/export"}],
        "links": [],
    }
    with patch(
        "app.services.workflow_definition_service.get_definition",
        return_value=definition,
    ):
        payload = _build_submit_payload("gee_demo", {})
    assert payload.gee_request is not None, 'payload.gee_request is not None'
    gr = payload.gee_request
    if hasattr(gr, "model_dump"):
        gr = gr.model_dump()
    assert gr.get("workflow_id") == "gee_demo", 'gr.get("workflow_id") == "gee_demo"'
    assert gr.get("workflow") is not None, 'gr.get("workflow") is not None'


def test_overrides_win_over_engine_inject() -> None:
    definition = {
        "_meta": {
            "engine": "python_provider",
            "linked_layer_id": "omega-avg-daily",
        },
        "workflow_id": "omega_avg_daily_smap_single",
        "nodes": [],
        "links": [],
    }
    overrides = {
        "algorithm_request": {
            "module_name": "custom_module",
            "algorithm_params": {"tb_source": "OVERRIDE"},
        },
        "layer_id": "custom-layer",
    }
    with patch(
        "app.services.workflow_definition_service.get_definition",
        return_value=definition,
    ):
        payload = _build_submit_payload("omega_avg_daily_smap_single", overrides)
    assert payload.layer_id == "custom-layer", 'payload.layer_id == "custom-layer"'
    algo = payload.algorithm_request
    if hasattr(algo, "model_dump"):
        algo = algo.model_dump()
    elif hasattr(algo, "dict"):
        algo = algo.dict()
    assert algo.get("module_name") == "custom_module", 'algo.get("module_name") == "custom_module"'
    assert algo.get("algorithm_params", {}).get("tb_source") == "OVERRIDE", 'algo.get("algorithm_params", {}).get("tb_source") == "OVERRIDE"'
    # 显式 algorithm_request 时不注入 workflow_name 默认路径
    assert algo.get("workflow_name") != "omega_avg_daily_smap_single", 'algo.get("workflow_name") != "omega_avg_daily_smap_single"'


@pytest.fixture
def _tick_emit_trigger_tests_env():
    ns = types.SimpleNamespace()
    ns._tmpdir = tempfile.TemporaryDirectory()
    ns._store = WorkflowTimerStore(state_dir=Path(ns._tmpdir.name))
    ns._patcher_store = patch(
        "app.services.workflow_timer_service.get_timer_store",
        return_value=ns._store,
    )
    ns._patcher_store.start()
    yield ns
    ns._patcher_store.stop()
    ns._store.close()
    ns._tmpdir.cleanup()


def _make_due_timer(store) -> WorkflowTimer:
    timer = WorkflowTimer(
        timer_id="timer-tick1",
        workflow_id="wf-1",
        name="Tick Test",
        trigger_type="cron",
        trigger_config={"cron": "0 8 * * *"},
        enabled=True,
        next_fire_at="2020-01-01T00:00:00+00:00",
        created_at="2026-07-21T00:00:00+00:00",
        updated_at="2026-07-21T00:00:00+00:00",
    )
    store.create_timer(timer)
    return timer


def test_tick_fires_due_timer(_tick_emit_trigger_tests_env) -> None:
    self = _tick_emit_trigger_tests_env
    with patch("app.services.workflow_timer_service._build_submit_payload") as mock_build:
        _make_due_timer(self._store)
        mock_build.return_value = MagicMock()
        with patch(
            "app.services.workflow.service_container.submission_service"
        ) as mock_sub:
            mock_sub.submit_workflow.return_value = MagicMock(run_id="run-tick-1")
            stats = tick()
        assert stats["checked"] == 1, 'stats["checked"] == 1'
        assert stats["fired"] == 1, 'stats["fired"] == 1'
        assert stats["failed"] == 0, 'stats["failed"] == 0'
        assert stats["skipped"] == 0, 'stats["skipped"] == 0'
        assert stats["reclaimed"] == 0, 'stats["reclaimed"] == 0'
        loaded = self._store.get_timer("timer-tick1")
        assert loaded.last_run_id == "run-tick-1", 'loaded.last_run_id == "run-tick-1"'
        assert loaded.fire_count == 1, 'loaded.fire_count == 1'
        assert loaded.next_fire_at is not None, 'loaded.next_fire_at is not None'
        assert not str(loaded.next_fire_at).startswith("CLAIMED:"), 'str(loaded.next_fire_at).startswith("CLAIMED:") is falsy'

def test_tick_reclaims_stale_then_fires(_tick_emit_trigger_tests_env) -> None:
    self = _tick_emit_trigger_tests_env
    with patch("app.services.workflow_timer_service._build_submit_payload") as mock_build:
        timer = WorkflowTimer(
            timer_id="timer-stale",
            workflow_id="wf-1",
            name="Stale Claim",
            trigger_type="cron",
            trigger_config={"cron": "0 8 * * *"},
            enabled=True,
            next_fire_at="CLAIMED:2020-01-01T00:00:00+00:00:deadbeef",
            created_at="2020-01-01T00:00:00+00:00",
            updated_at="2020-01-01T00:00:00+00:00",
        )
        self._store.create_timer(timer)
        mock_build.return_value = MagicMock()
        with patch(
            "app.services.workflow.service_container.submission_service"
        ) as mock_sub:
            mock_sub.submit_workflow.return_value = MagicMock(run_id="run-reclaim-1")
            stats = tick()
        assert stats["reclaimed"] == 1, 'stats["reclaimed"] == 1'
        assert stats["fired"] == 1, 'stats["fired"] == 1'
        loaded = self._store.get_timer("timer-stale")
        assert loaded.last_run_id == "run-reclaim-1", 'loaded.last_run_id == "run-reclaim-1"'
        assert not str(loaded.next_fire_at).startswith("CLAIMED:"), 'str(loaded.next_fire_at).startswith("CLAIMED:") is falsy'

def test_tick_records_failure(_tick_emit_trigger_tests_env) -> None:
    self = _tick_emit_trigger_tests_env
    with patch("app.services.workflow_timer_service._build_submit_payload") as mock_build:
        _make_due_timer(self._store)
        mock_build.side_effect = RuntimeError("payload build failed")
        stats = tick()
        assert stats["checked"] == 1, 'stats["checked"] == 1'
        assert stats["fired"] == 0, 'stats["fired"] == 0'
        assert stats["failed"] == 1, 'stats["failed"] == 1'
        loaded = self._store.get_timer("timer-tick1")
        assert loaded.last_run_id is None, 'loaded.last_run_id is None'
        assert "RuntimeError" in loaded.last_error or "", '"RuntimeError" in loaded.last_error or ""'

def test_emit_event_triggers_matching_timer(_tick_emit_trigger_tests_env) -> None:
    self = _tick_emit_trigger_tests_env
    with patch("app.services.workflow_timer_service._build_submit_payload") as mock_build:
        timer = WorkflowTimer(
            timer_id="timer-evt1",
            workflow_id="wf-1",
            name="Event Timer",
            trigger_type="event",
            trigger_config={"event_type": "data_ready"},
            enabled=True,
            created_at="2026-07-21T00:00:00+00:00",
            updated_at="2026-07-21T00:00:00+00:00",
        )
        self._store.create_timer(timer)

        mock_build.return_value = MagicMock()
        with patch(
            "app.services.workflow.service_container.submission_service"
        ) as mock_sub:
            mock_sub.submit_workflow.return_value = MagicMock(run_id="run-evt-1")
            stats = emit_event("data_ready", {"key": "value"})

        assert stats["matched"] == 1, 'stats["matched"] == 1'
        assert stats["fired"] == 1, 'stats["fired"] == 1'
        assert stats["failed"] == 0, 'stats["failed"] == 0'
        loaded = self._store.get_timer("timer-evt1")
        assert loaded.last_run_id == "run-evt-1", 'loaded.last_run_id == "run-evt-1"'

def test_emit_event_no_match(_tick_emit_trigger_tests_env) -> None:
    self = _tick_emit_trigger_tests_env
    with patch("app.services.workflow_timer_service._build_submit_payload") as mock_build:
        stats = emit_event("nonexistent_event")
        assert stats["matched"] == 0, 'stats["matched"] == 0'
        assert stats["fired"] == 0, 'stats["fired"] == 0'
        mock_build.assert_not_called()

def test_trigger_manually(_tick_emit_trigger_tests_env) -> None:
    self = _tick_emit_trigger_tests_env
    with patch("app.services.workflow_timer_service._build_submit_payload") as mock_build:
        timer = WorkflowTimer(
            timer_id="timer-manual1",
            workflow_id="wf-1",
            name="Manual Test",
            trigger_type="cron",
            trigger_config={"cron": "0 8 * * *"},
            enabled=True,
            next_fire_at="2099-12-31T23:59:00+00:00",
            created_at="2026-07-21T00:00:00+00:00",
            updated_at="2026-07-21T00:00:00+00:00",
        )
        self._store.create_timer(timer)

        mock_build.return_value = MagicMock()
        with patch(
            "app.services.workflow.service_container.submission_service"
        ) as mock_sub:
            mock_sub.submit_workflow.return_value = MagicMock(
                run_id="run-manual-1",
                status_url="/workflow-runs/run-manual-1",
            )
            result = trigger_manually("timer-manual1")

        assert result["timer_id"] == "timer-manual1", 'result["timer_id"] == "timer-manual1"'
        assert result["run_id"] == "run-manual-1", 'result["run_id"] == "run-manual-1"'
        loaded = self._store.get_timer("timer-manual1")
        assert loaded.last_run_id == "run-manual-1", 'loaded.last_run_id == "run-manual-1"'
        assert loaded.next_fire_at == "2099-12-31T23:59:00+00:00", 'loaded.next_fire_at == "2099-12-31T23:59:00+00:00"'
