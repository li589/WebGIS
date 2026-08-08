"""Tests for app.services.workflow_timer_service.

覆盖：
- cron 解析（语法 + 边界 + Asia/Shanghai 墙钟）
- 触发器配置校验 / interval clamp
- WorkflowTimerStore CRUD / claim
- tick() / emit_event() / trigger_manually()（mock submission_service）
- _build_submit_payload 按 engine 注入
"""

from __future__ import annotations

import tempfile
import unittest
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


class CronParserTests(unittest.TestCase):
    def test_parse_wildcard(self) -> None:
        result = parse_cron("* * * * *")
        self.assertEqual(result["minute"], set(range(60)))
        self.assertEqual(result["hour"], set(range(24)))
        self.assertEqual(result["day_of_month"], set(range(1, 32)))
        self.assertEqual(result["month"], set(range(1, 13)))
        self.assertEqual(result["day_of_week"], set(range(7)))

    def test_parse_step(self) -> None:
        result = parse_cron("*/15 * * * *")
        self.assertEqual(result["minute"], {0, 15, 30, 45})

    def test_parse_list(self) -> None:
        result = parse_cron("0,30 * * * *")
        self.assertEqual(result["minute"], {0, 30})

    def test_parse_range(self) -> None:
        result = parse_cron("0 9-17 * * *")
        self.assertEqual(result["hour"], set(range(9, 18)))

    def test_parse_range_with_step(self) -> None:
        result = parse_cron("0 9-17/2 * * *")
        self.assertEqual(result["hour"], {9, 11, 13, 15, 17})

    def test_parse_invalid_field_count(self) -> None:
        with self.assertRaises(TimerValidationError):
            parse_cron("* * * *")
        with self.assertRaises(TimerValidationError):
            parse_cron("* * * * * *")

    def test_parse_out_of_range(self) -> None:
        with self.assertRaises(TimerValidationError):
            parse_cron("60 * * * *")
        with self.assertRaises(TimerValidationError):
            parse_cron("* 24 * * *")
        with self.assertRaises(TimerValidationError):
            parse_cron("* * 0 * *")

    def test_parse_invalid_value(self) -> None:
        with self.assertRaises(TimerValidationError):
            parse_cron("abc * * * *")

    def test_next_cron_time_shanghai_wall_clock(self) -> None:
        # 0 8 * * * = 每天北京时间 08:00 = UTC 00:00（无夏令时）
        # 2026-07-21 07:30 UTC = 15:30 上海 → 下次为 7/22 08:00 上海 = 7/22 00:00 UTC
        after = datetime(2026, 7, 21, 7, 30, tzinfo=timezone.utc)
        nxt = next_cron_time("0 8 * * *", after)
        self.assertEqual(nxt.astimezone(timezone.utc), datetime(2026, 7, 22, 0, 0, tzinfo=timezone.utc))
        local = nxt.astimezone(SHANGHAI)
        self.assertEqual(local.hour, 8)
        self.assertEqual(local.minute, 0)

    def test_next_cron_time_same_day_shanghai(self) -> None:
        # 北京时间 07:30 → 当天 08:00 上海
        after = datetime(2026, 7, 21, 7, 30, tzinfo=SHANGHAI).astimezone(timezone.utc)
        nxt = next_cron_time("0 8 * * *", after)
        local = nxt.astimezone(SHANGHAI)
        self.assertEqual(local.day, 21)
        self.assertEqual(local.hour, 8)

    def test_next_cron_time_weekday_filter(self) -> None:
        # 0 8 * * 1 = 每周一 08:00 上海
        # 2026-07-21 是周二
        after = datetime(2026, 7, 21, 9, 0, tzinfo=SHANGHAI).astimezone(timezone.utc)
        nxt = next_cron_time("0 8 * * 1", after)
        local = nxt.astimezone(SHANGHAI)
        self.assertEqual(local.day, 27)  # 下周一
        self.assertEqual(local.hour, 8)

    def test_timer_tz_constant(self) -> None:
        self.assertEqual(str(TIMER_TZ), "Asia/Shanghai")


class TriggerConfigValidationTests(unittest.TestCase):
    def test_validate_cron(self) -> None:
        cfg = validate_trigger_config("cron", {"cron": "0 8 * * *"})
        self.assertEqual(cfg, {"cron": "0 8 * * *"})

    def test_validate_cron_invalid(self) -> None:
        with self.assertRaises(TimerValidationError):
            validate_trigger_config("cron", {"cron": "invalid"})
        with self.assertRaises(TimerValidationError):
            validate_trigger_config("cron", {})

    def test_validate_interval(self) -> None:
        cfg = validate_trigger_config("interval", {"seconds": 3600})
        self.assertEqual(cfg, {"seconds": 3600})

    def test_validate_interval_too_small(self) -> None:
        with self.assertRaises(TimerValidationError):
            validate_trigger_config("interval", {"seconds": 30})
        with self.assertRaises(TimerValidationError):
            validate_trigger_config("interval", {"seconds": "abc"})

    def test_validate_event(self) -> None:
        cfg = validate_trigger_config("event", {"event_type": "data_ready"})
        self.assertEqual(cfg, {"event_type": "data_ready"})

    def test_validate_event_empty(self) -> None:
        with self.assertRaises(TimerValidationError):
            validate_trigger_config("event", {"event_type": ""})

    def test_validate_unknown_type(self) -> None:
        with self.assertRaises(TimerValidationError):
            validate_trigger_config("unknown", {})

    def test_compute_next_fire_at_cron(self) -> None:
        result = compute_next_fire_at("cron", {"cron": "0 8 * * *"}, None)
        self.assertIsNotNone(result)
        self.assertIn("T", result)

    def test_compute_next_fire_at_interval_from_last(self) -> None:
        now = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)
        last = datetime(2026, 7, 21, 11, 30, tzinfo=timezone.utc)
        result = compute_next_fire_at(
            "interval", {"seconds": 3600}, last, now=now
        )
        self.assertEqual(result, "2026-07-21T12:30:00+00:00")

    def test_compute_next_fire_at_interval_clamps_past(self) -> None:
        now = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)
        last = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)
        result = compute_next_fire_at(
            "interval", {"seconds": 3600}, last, now=now
        )
        self.assertEqual(result, "2026-08-05T13:00:00+00:00")

    def test_compute_next_fire_at_event_returns_none(self) -> None:
        result = compute_next_fire_at("event", {"event_type": "x"}, None)
        self.assertIsNone(result)


class DateTemplateTests(unittest.TestCase):
    def test_resolve_today_shape(self) -> None:
        result = resolve_date_templates("{{today}}")
        self.assertIsInstance(result, int)
        self.assertEqual(len(str(result)), 8)

    def test_resolve_nested_dict(self) -> None:
        result = resolve_date_templates({"start": "{{today}}", "label": "x"})
        self.assertIsInstance(result["start"], int)
        self.assertEqual(result["label"], "x")


class WorkflowTimerStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.store = WorkflowTimerStore(state_dir=Path(self._tmpdir.name))

    def tearDown(self) -> None:
        self.store.close()
        self._tmpdir.cleanup()

    def _make_timer(self, timer_id: str = "timer-test1") -> WorkflowTimer:
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

    def test_create_and_get_timer(self) -> None:
        timer = self._make_timer()
        self.store.create_timer(timer)
        loaded = self.store.get_timer("timer-test1")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.workflow_id, "wf-1")
        self.assertEqual(loaded.trigger_config, {"cron": "0 8 * * *"})
        self.assertTrue(loaded.enabled)

    def test_list_timers(self) -> None:
        self.store.create_timer(self._make_timer("t1"))
        self.store.create_timer(self._make_timer("t2"))
        all_timers = self.store.list_timers()
        self.assertEqual(len(all_timers), 2)
        filtered = self.store.list_timers(workflow_id="wf-1")
        self.assertEqual(len(filtered), 2)
        filtered_none = self.store.list_timers(workflow_id="nonexistent")
        self.assertEqual(len(filtered_none), 0)

    def test_delete_timer(self) -> None:
        self.store.create_timer(self._make_timer())
        self.assertTrue(self.store.delete_timer("timer-test1"))
        self.assertIsNone(self.store.get_timer("timer-test1"))
        self.assertFalse(self.store.delete_timer("timer-test1"))

    def test_update_timer_enable_disable(self) -> None:
        self.store.create_timer(self._make_timer())
        updated = self.store.update_timer("timer-test1", {"enabled": False})
        self.assertFalse(updated.enabled)
        self.assertIsNone(updated.next_fire_at)
        updated = self.store.update_timer("timer-test1", {"enabled": True})
        self.assertTrue(updated.enabled)
        self.assertIsNotNone(updated.next_fire_at)

    def test_update_timer_change_trigger(self) -> None:
        self.store.create_timer(self._make_timer())
        updated = self.store.update_timer(
            "timer-test1",
            {"trigger_type": "interval", "trigger_config": {"seconds": 7200}},
        )
        self.assertEqual(updated.trigger_type, "interval")
        self.assertEqual(updated.trigger_config, {"seconds": 7200})
        self.assertIsNotNone(updated.next_fire_at)

    def test_update_timer_type_without_config_rejected(self) -> None:
        self.store.create_timer(self._make_timer())
        with self.assertRaises(TimerValidationError):
            self.store.update_timer("timer-test1", {"trigger_type": "interval"})

    def test_fetch_due_timers(self) -> None:
        past_time = "2020-01-01T00:00:00+00:00"
        timer = self._make_timer()
        timer.next_fire_at = past_time
        self.store.create_timer(timer)
        future_timer = self._make_timer("timer-future")
        future_timer.next_fire_at = "2099-12-31T23:59:00+00:00"
        self.store.create_timer(future_timer)

        due = self.store.fetch_due_timers(datetime(2026, 7, 21, tzinfo=timezone.utc))
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0].timer_id, "timer-test1")

    def test_fetch_due_timers_excludes_event_type(self) -> None:
        timer = self._make_timer()
        timer.trigger_type = "event"
        timer.trigger_config = {"event_type": "data_ready"}
        timer.next_fire_at = "2020-01-01T00:00:00+00:00"
        self.store.create_timer(timer)

        due = self.store.fetch_due_timers(datetime(2026, 7, 21, tzinfo=timezone.utc))
        self.assertEqual(len(due), 0)

    def test_claim_due_timers_idempotent(self) -> None:
        timer = self._make_timer()
        timer.next_fire_at = "2020-01-01T00:00:00+00:00"
        self.store.create_timer(timer)
        now = datetime(2026, 7, 21, tzinfo=timezone.utc)
        claimed1, skipped1 = self.store.claim_due_timers(now)
        self.assertEqual(len(claimed1), 1)
        self.assertEqual(skipped1, 0)
        claimed2, skipped2 = self.store.claim_due_timers(now)
        self.assertEqual(len(claimed2), 0)
        self.assertEqual(skipped2, 0)  # 已不在 due 列表
        loaded = self.store.get_timer("timer-test1")
        self.assertTrue(str(loaded.next_fire_at).startswith("CLAIMED:"))

    def test_claim_skips_when_next_fire_raced(self) -> None:
        """fetch 后 next_fire_at 被改写 → UPDATE 乐观锁失败计入 skipped。"""
        timer = self._make_timer()
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
        self.assertEqual(len(claimed), 0)
        self.assertEqual(skipped, 1)

    def test_reclaim_stale_claims(self) -> None:
        timer = self._make_timer()
        timer.next_fire_at = "CLAIMED:2020-01-01T00:00:00+00:00:deadbeef"
        timer.updated_at = "2020-01-01T00:00:00+00:00"
        self.store.create_timer(timer)
        now = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)
        reclaimed = self.store.reclaim_stale_claims(now, ttl_seconds=CLAIM_TTL_SECONDS)
        self.assertEqual(reclaimed, 1)
        loaded = self.store.get_timer("timer-test1")
        self.assertEqual(loaded.next_fire_at, now.isoformat())
        # 新鲜 CLAIMED（updated_at=now）不应被回收
        timer2 = self._make_timer("timer-fresh")
        timer2.next_fire_at = f"CLAIMED:{now.isoformat()}:abcdef12"
        timer2.updated_at = now.isoformat()
        self.store.create_timer(timer2)
        reclaimed2 = self.store.reclaim_stale_claims(now, ttl_seconds=CLAIM_TTL_SECONDS)
        self.assertEqual(reclaimed2, 0)
        self.assertTrue(
            str(self.store.get_timer("timer-fresh").next_fire_at).startswith("CLAIMED:")
        )

    def test_find_event_timers(self) -> None:
        timer = self._make_timer()
        timer.trigger_type = "event"
        timer.trigger_config = {"event_type": "data_ready"}
        self.store.create_timer(timer)

        result = self.store.find_event_timers("other_event")
        self.assertEqual(len(result), 0)
        result = self.store.find_event_timers("data_ready")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].timer_id, "timer-test1")

    def test_mark_fired(self) -> None:
        self.store.create_timer(self._make_timer())
        self.store.mark_fired(
            "timer-test1",
            run_id="run-abc",
            error=None,
            next_fire_at="2026-07-22T08:00:00+00:00",
        )
        loaded = self.store.get_timer("timer-test1")
        self.assertEqual(loaded.last_run_id, "run-abc")
        self.assertIsNone(loaded.last_error)
        self.assertEqual(loaded.fire_count, 1)
        self.assertEqual(loaded.next_fire_at, "2026-07-22T08:00:00+00:00")
        self.assertIsNotNone(loaded.last_fired_at)


class BuildSubmitPayloadTests(unittest.TestCase):
    def test_python_provider_injects_workflow_name(self) -> None:
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
        self.assertEqual(algo.get("workflow_name"), "omega_avg_daily_smap_single")
        self.assertIsNotNone(algo.get("workflow_definition"))
        self.assertEqual(algo.get("algorithm_params", {}).get("tb_source"), "SMAP")
        self.assertEqual(payload.layer_id, "omega-avg-daily")

    def test_weather_injects_weather_request(self) -> None:
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
        self.assertIsNotNone(payload.weather_request)
        wr = payload.weather_request
        if hasattr(wr, "model_dump"):
            wr = wr.model_dump()
        self.assertEqual(wr.get("workflow_id"), "weather_temperature_grid_demo")
        self.assertEqual(wr.get("layer_id"), "temperature")

    def test_gee_injects_gee_request(self) -> None:
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
        self.assertIsNotNone(payload.gee_request)
        gr = payload.gee_request
        if hasattr(gr, "model_dump"):
            gr = gr.model_dump()
        self.assertEqual(gr.get("workflow_id"), "gee_demo")
        self.assertIsNotNone(gr.get("workflow"))

    def test_overrides_win_over_engine_inject(self) -> None:
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
        self.assertEqual(payload.layer_id, "custom-layer")
        algo = payload.algorithm_request
        if hasattr(algo, "model_dump"):
            algo = algo.model_dump()
        elif hasattr(algo, "dict"):
            algo = algo.dict()
        self.assertEqual(algo.get("module_name"), "custom_module")
        self.assertEqual(algo.get("algorithm_params", {}).get("tb_source"), "OVERRIDE")
        # 显式 algorithm_request 时不注入 workflow_name 默认路径
        self.assertNotEqual(algo.get("workflow_name"), "omega_avg_daily_smap_single")


class TickEmitTriggerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._store = WorkflowTimerStore(state_dir=Path(self._tmpdir.name))
        self._patcher_store = patch(
            "app.services.workflow_timer_service.get_timer_store",
            return_value=self._store,
        )
        self._patcher_store.start()

    def tearDown(self) -> None:
        self._patcher_store.stop()
        self._store.close()
        self._tmpdir.cleanup()

    def _make_due_timer(self) -> WorkflowTimer:
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
        self._store.create_timer(timer)
        return timer

    @patch("app.services.workflow_timer_service._build_submit_payload")
    def test_tick_fires_due_timer(self, mock_build: MagicMock) -> None:
        self._make_due_timer()
        mock_build.return_value = MagicMock()
        with patch(
            "app.services.workflow.service_container.submission_service"
        ) as mock_sub:
            mock_sub.submit_workflow.return_value = MagicMock(run_id="run-tick-1")
            stats = tick()
        self.assertEqual(stats["checked"], 1)
        self.assertEqual(stats["fired"], 1)
        self.assertEqual(stats["failed"], 0)
        self.assertEqual(stats["skipped"], 0)
        self.assertEqual(stats["reclaimed"], 0)
        loaded = self._store.get_timer("timer-tick1")
        self.assertEqual(loaded.last_run_id, "run-tick-1")
        self.assertEqual(loaded.fire_count, 1)
        self.assertIsNotNone(loaded.next_fire_at)
        self.assertFalse(str(loaded.next_fire_at).startswith("CLAIMED:"))

    @patch("app.services.workflow_timer_service._build_submit_payload")
    def test_tick_reclaims_stale_then_fires(self, mock_build: MagicMock) -> None:
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
        self.assertEqual(stats["reclaimed"], 1)
        self.assertEqual(stats["fired"], 1)
        loaded = self._store.get_timer("timer-stale")
        self.assertEqual(loaded.last_run_id, "run-reclaim-1")
        self.assertFalse(str(loaded.next_fire_at).startswith("CLAIMED:"))

    @patch("app.services.workflow_timer_service._build_submit_payload")
    def test_tick_records_failure(self, mock_build: MagicMock) -> None:
        self._make_due_timer()
        mock_build.side_effect = RuntimeError("payload build failed")
        stats = tick()
        self.assertEqual(stats["checked"], 1)
        self.assertEqual(stats["fired"], 0)
        self.assertEqual(stats["failed"], 1)
        loaded = self._store.get_timer("timer-tick1")
        self.assertIsNone(loaded.last_run_id)
        self.assertIn("RuntimeError", loaded.last_error or "")

    @patch("app.services.workflow_timer_service._build_submit_payload")
    def test_emit_event_triggers_matching_timer(self, mock_build: MagicMock) -> None:
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

        self.assertEqual(stats["matched"], 1)
        self.assertEqual(stats["fired"], 1)
        self.assertEqual(stats["failed"], 0)
        loaded = self._store.get_timer("timer-evt1")
        self.assertEqual(loaded.last_run_id, "run-evt-1")

    @patch("app.services.workflow_timer_service._build_submit_payload")
    def test_emit_event_no_match(self, mock_build: MagicMock) -> None:
        stats = emit_event("nonexistent_event")
        self.assertEqual(stats["matched"], 0)
        self.assertEqual(stats["fired"], 0)
        mock_build.assert_not_called()

    @patch("app.services.workflow_timer_service._build_submit_payload")
    def test_trigger_manually(self, mock_build: MagicMock) -> None:
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

        self.assertEqual(result["timer_id"], "timer-manual1")
        self.assertEqual(result["run_id"], "run-manual-1")
        loaded = self._store.get_timer("timer-manual1")
        self.assertEqual(loaded.last_run_id, "run-manual-1")
        self.assertEqual(loaded.next_fire_at, "2099-12-31T23:59:00+00:00")


if __name__ == "__main__":
    unittest.main()
