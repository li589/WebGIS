"""Tests for app.services.workflow_timer_service.

覆盖：
- cron 解析（语法 + 边界）
- 触发器配置校验
- WorkflowTimerStore CRUD
- tick() / emit_event() / trigger_manually() 业务逻辑（mock submission_service）
"""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.services.workflow_timer_service import (
    TimerValidationError,
    WorkflowTimer,
    WorkflowTimerStore,
    compute_next_fire_at,
    next_cron_time,
    parse_cron,
    tick,
    emit_event,
    trigger_manually,
    validate_trigger_config,
)


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
            parse_cron("* * * *")  # 4 fields
        with self.assertRaises(TimerValidationError):
            parse_cron("* * * * * *")  # 6 fields

    def test_parse_out_of_range(self) -> None:
        with self.assertRaises(TimerValidationError):
            parse_cron("60 * * * *")  # minute > 59
        with self.assertRaises(TimerValidationError):
            parse_cron("* 24 * * *")  # hour > 23
        with self.assertRaises(TimerValidationError):
            parse_cron("* * 0 * *")  # day_of_month < 1

    def test_parse_invalid_value(self) -> None:
        with self.assertRaises(TimerValidationError):
            parse_cron("abc * * * *")

    def test_next_cron_time_basic(self) -> None:
        # 0 8 * * * = 每天 08:00
        after = datetime(2026, 7, 21, 7, 30, tzinfo=timezone.utc)
        nxt = next_cron_time("0 8 * * *", after)
        self.assertEqual(nxt.hour, 8)
        self.assertEqual(nxt.minute, 0)
        self.assertEqual(nxt.day, 21)

    def test_next_cron_time_skip_to_next_day(self) -> None:
        # 0 8 * * * = 每天 08:00
        after = datetime(2026, 7, 21, 9, 0, tzinfo=timezone.utc)
        nxt = next_cron_time("0 8 * * *", after)
        self.assertEqual(nxt.day, 22)
        self.assertEqual(nxt.hour, 8)

    def test_next_cron_time_weekday_filter(self) -> None:
        # 0 8 * * 1 = 每周一 08:00（cron weekday 1=Monday）
        # 2026-07-21 是周二（py_wd=1, cron_wd=2）
        after = datetime(2026, 7, 21, 9, 0, tzinfo=timezone.utc)
        nxt = next_cron_time("0 8 * * 1", after)
        # 下周一应该是 2026-07-27
        self.assertEqual(nxt.day, 27)
        self.assertEqual(nxt.hour, 8)


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
        # Should be ISO format
        self.assertIn("T", result)

    def test_compute_next_fire_at_interval(self) -> None:
        last = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)
        result = compute_next_fire_at("interval", {"seconds": 3600}, last)
        self.assertEqual(result, "2026-07-21T13:00:00+00:00")

    def test_compute_next_fire_at_event_returns_none(self) -> None:
        result = compute_next_fire_at("event", {"event_type": "x"}, None)
        self.assertIsNone(result)


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
        # by workflow_id
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
        # Re-enable should recompute next_fire_at
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

    def test_fetch_due_timers(self) -> None:
        # 创建一个已到期的定时器
        past_time = "2020-01-01T00:00:00+00:00"
        timer = self._make_timer()
        timer.next_fire_at = past_time
        self.store.create_timer(timer)
        # 创建一个未到期的定时器
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
        timer.next_fire_at = "2020-01-01T00:00:00+00:00"  # 已过期但仍不应被 fetch
        self.store.create_timer(timer)

        due = self.store.fetch_due_timers(datetime(2026, 7, 21, tzinfo=timezone.utc))
        self.assertEqual(len(due), 0)

    def test_find_event_timers(self) -> None:
        timer = self._make_timer()
        timer.trigger_type = "event"
        timer.trigger_config = {"event_type": "data_ready"}
        self.store.create_timer(timer)

        # 不匹配的 event_type
        result = self.store.find_event_timers("other_event")
        self.assertEqual(len(result), 0)
        # 匹配的 event_type
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


class TickEmitTriggerTests(unittest.TestCase):
    """测试业务逻辑函数：tick / emit_event / trigger_manually。

    使用 patch 替换 submission_service.submit_workflow 和 wds.get_definition，
    避免依赖真实的工作流定义文件和 Celery 任务派发。
    """

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        # 替换全局 store 单例
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
            next_fire_at="2020-01-01T00:00:00+00:00",  # 已到期
            created_at="2026-07-21T00:00:00+00:00",
            updated_at="2026-07-21T00:00:00+00:00",
        )
        self._store.create_timer(timer)
        return timer

    @patch("app.services.workflow_timer_service._build_submit_payload")
    def test_tick_fires_due_timer(self, mock_build: MagicMock) -> None:
        self._make_due_timer()
        mock_build.return_value = MagicMock()
        with patch("app.services.workflow.service_container.submission_service") as mock_sub:
            mock_sub.submit_workflow.return_value = MagicMock(run_id="run-tick-1")
            stats = tick()
        self.assertEqual(stats["checked"], 1)
        self.assertEqual(stats["fired"], 1)
        self.assertEqual(stats["failed"], 0)
        loaded = self._store.get_timer("timer-tick1")
        self.assertEqual(loaded.last_run_id, "run-tick-1")
        self.assertEqual(loaded.fire_count, 1)
        self.assertIsNotNone(loaded.next_fire_at)  # 应已计算下次触发

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
        with patch("app.services.workflow.service_container.submission_service") as mock_sub:
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
            next_fire_at="2099-12-31T23:59:00+00:00",  # 未到期
            created_at="2026-07-21T00:00:00+00:00",
            updated_at="2026-07-21T00:00:00+00:00",
        )
        self._store.create_timer(timer)

        mock_build.return_value = MagicMock()
        with patch("app.services.workflow.service_container.submission_service") as mock_sub:
            mock_sub.submit_workflow.return_value = MagicMock(
                run_id="run-manual-1",
                status_url="/workflow-runs/run-manual-1",
            )
            result = trigger_manually("timer-manual1")

        self.assertEqual(result["timer_id"], "timer-manual1")
        self.assertEqual(result["run_id"], "run-manual-1")
        loaded = self._store.get_timer("timer-manual1")
        self.assertEqual(loaded.last_run_id, "run-manual-1")
        # 手动触发不应改变 next_fire_at
        self.assertEqual(loaded.next_fire_at, "2099-12-31T23:59:00+00:00")


if __name__ == "__main__":
    unittest.main()
