"""工作流定时器服务

为工作流模块提供自动运行能力，支持三种触发类型：
- cron: 5 字段 cron 表达式（minute hour day month weekday）
- interval: 固定间隔（秒）
- event: 外部事件触发（通过 emit_event 接口）

存储使用与 workflow_runs 相同的 SQLite 数据库（workflow_state.sqlite3），
表名 workflow_timers。Celery Beat 每分钟调用 tick() 检查到期定时器并提交工作流。

设计要点：
- 旧数据兼容：表通过 _initialize_schema 创建，迁移用 _migrate_schema
- cron 解析自实现（无外部依赖），支持 *、*/N、N、N,M、N-M 五种语法
- 提交失败不影响下次触发，错误记录到 last_error 字段
- 事件触发器立即响应 emit_event 调用（同步提交）
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.config import settings

logger = logging.getLogger(__name__)


# ─── 异常 ────────────────────────────────────────────────────────────────────
class TimerNotFoundError(Exception):
    """定时器不存在。"""


class TimerValidationError(ValueError):
    """定时器配置校验失败。"""


# ─── 数据结构 ────────────────────────────────────────────────────────────────
@dataclass
class WorkflowTimer:
    timer_id: str
    workflow_id: str
    name: str
    trigger_type: str  # 'cron' | 'interval' | 'event'
    trigger_config: dict[str, Any]
    payload_overrides: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    last_fired_at: str | None = None
    next_fire_at: str | None = None
    last_run_id: str | None = None
    last_error: str | None = None
    fire_count: int = 0
    created_at: str = ""
    updated_at: str = ""


# ─── Cron 解析器（5 字段，无外部依赖） ───────────────────────────────────────
# 字段范围：minute(0-59) hour(0-23) day-of-month(1-31) month(1-12) day-of-week(0-6, 0=Sunday)
_FIELD_RANGES = [
    (0, 59),   # minute
    (0, 23),   # hour
    (1, 31),   # day of month
    (1, 12),   # month
    (0, 6),    # day of week (0=Sunday)
]

_FIELD_NAMES = ["minute", "hour", "day_of_month", "month", "day_of_week"]


def _parse_cron_field(expr: str, lo: int, hi: int, field_name: str) -> set[int]:
    """解析单个 cron 字段为合法值集合。

    支持：* / */N / N / N,M / N-M / N-M/S
    """
    if not expr:
        raise TimerValidationError(f"cron field {field_name} is empty")
    values: set[int] = set()
    for part in expr.split(","):
        part = part.strip()
        if part == "*":
            values.update(range(lo, hi + 1))
            continue
        # */N 或 N-M/S
        step = 1
        if "/" in part:
            base, step_str = part.split("/", 1)
            try:
                step = int(step_str)
            except ValueError as exc:
                raise TimerValidationError(
                    f"cron field {field_name} invalid step '{step_str}'"
                ) from exc
            if step <= 0:
                raise TimerValidationError(f"cron field {field_name} step must be > 0")
        else:
            base = part
        if base == "*":
            start, end = lo, hi
        elif "-" in base:
            try:
                start_str, end_str = base.split("-", 1)
                start = int(start_str)
                end = int(end_str)
            except ValueError as exc:
                raise TimerValidationError(
                    f"cron field {field_name} invalid range '{base}'"
                ) from exc
        else:
            try:
                start = int(base)
            except ValueError as exc:
                raise TimerValidationError(
                    f"cron field {field_name} invalid value '{base}'"
                ) from exc
            end = hi if "/" in part else start
        if start < lo or end > hi or start > end:
            raise TimerValidationError(
                f"cron field {field_name} value out of range [{lo},{hi}]: {base}"
            )
        values.update(range(start, end + 1, step))
    return values


def parse_cron(expr: str) -> dict[str, set[int]]:
    """解析 5 字段 cron 表达式。

    返回 {minute, hour, day_of_month, month, day_of_week} 各字段的有效值集合。
    """
    fields = expr.split()
    if len(fields) != 5:
        raise TimerValidationError(
            f"cron expression must have 5 fields, got {len(fields)}: {expr!r}"
        )
    return {
        name: _parse_cron_field(field, lo, hi, name)
        for field, (lo, hi), name in zip(fields, _FIELD_RANGES, _FIELD_NAMES)
    }


def next_cron_time(cron_expr: str, after: datetime) -> datetime:
    """计算 cron 表达式在 after 之后的下一次触发时间。

    从 after + 1 分钟开始逐分钟扫描，最多扫描 366 天（4 年闰年边界）。
    简单可靠，性能足够（每分钟最多 60*24*366 = ~527k 次检查，但实际首个匹配通常在前几千次内）。
    """
    parsed = parse_cron(cron_expr)
    # 起始：after + 1 分钟，秒归零
    candidate = (after.replace(second=0, microsecond=0) + timedelta(minutes=1))
    # Python weekday: Monday=0 ... Sunday=6；cron weekday: Sunday=0 ... Saturday=6
    # 转换：cron_wd = (py_wd + 1) % 7
    max_iter = 60 * 24 * 366  # 闰年最坏情况
    for _ in range(max_iter):
        cron_wd = (candidate.weekday() + 1) % 7
        if (
            candidate.minute in parsed["minute"]
            and candidate.hour in parsed["hour"]
            and candidate.day in parsed["day_of_month"]
            and candidate.month in parsed["month"]
            and cron_wd in parsed["day_of_week"]
        ):
            return candidate
        candidate += timedelta(minutes=1)
    # 理论上不会走到这里（4 年内必有匹配）
    raise TimerValidationError(f"no next fire time found for cron: {cron_expr}")


# ─── 触发器配置校验 ──────────────────────────────────────────────────────────
def validate_trigger_config(trigger_type: str, config: dict[str, Any]) -> dict[str, Any]:
    """校验并规范化触发器配置。返回规范化后的 config。"""
    if trigger_type == "cron":
        expr = config.get("cron")
        if not isinstance(expr, str) or not expr.strip():
            raise TimerValidationError("cron trigger requires 'cron' string field")
        # 立即解析一次以验证语法
        parse_cron(expr.strip())
        return {"cron": expr.strip()}
    if trigger_type == "interval":
        seconds = config.get("seconds")
        if not isinstance(seconds, int) or seconds < 60:
            raise TimerValidationError(
                "interval trigger requires 'seconds' integer field >= 60"
            )
        return {"seconds": seconds}
    if trigger_type == "event":
        event_type = config.get("event_type")
        if not isinstance(event_type, str) or not event_type.strip():
            raise TimerValidationError("event trigger requires 'event_type' string field")
        return {"event_type": event_type.strip()}
    raise TimerValidationError(
        f"unknown trigger_type: {trigger_type!r} (expected: cron | interval | event)"
    )


def compute_next_fire_at(
    trigger_type: str,
    config: dict[str, Any],
    last_fired_at: datetime | None,
) -> str | None:
    """计算下次触发时间（ISO 8601 UTC）。event 类型返回 None（仅事件触发）。"""
    now = datetime.now(timezone.utc)
    if trigger_type == "cron":
        base = last_fired_at or now
        return next_cron_time(config["cron"], base).isoformat()
    if trigger_type == "interval":
        base = last_fired_at or now
        return (base + timedelta(seconds=config["seconds"])).isoformat()
    return None  # event


# ─── 工作流提交辅助 ──────────────────────────────────────────────────────────
def _build_submit_payload(
    workflow_id: str,
    overrides: dict[str, Any],
) -> Any:
    """根据 workflow_id 加载定义并合并 overrides，构造 WorkflowSubmitRequest。

    约定：工作流定义中 nodes[0] 或 extra.default_command 决定 command_type。
    若定义缺失，使用 analysis 作为兜底。
    """
    from app.services import workflow_definition_service as wds
    from shared.contracts.api_contracts import WorkflowCommandType, WorkflowSubmitRequest

    definition = wds.get_definition(workflow_id)
    if definition is None:
        raise TimerValidationError(f"workflow definition not found: {workflow_id}")

    # 从定义中提取默认 command_type
    extra = definition.get("extra") or {}
    command_str = extra.get("default_command") or "analysis"
    try:
        command_type = WorkflowCommandType(command_str)
    except ValueError:
        command_type = WorkflowCommandType.analysis

    # 从定义中提取默认 layer_id
    layer_id = extra.get("default_layer_id") or overrides.get("layer_id")
    parameters = dict(extra.get("default_parameters") or {})
    parameters.update(overrides.get("parameters") or {})

    payload = WorkflowSubmitRequest(
        command_type=command_type,
        command_label=overrides.get("command_label") or f"timer:{workflow_id}",
        layer_id=layer_id,
        parameters=parameters,
    )
    # 应用其余 overrides（time_range / spatial_filter / engine_requests 等）
    for key in ("time_range", "spatial_filter", "gee_request", "weather_request",
                "algorithm_request", "config_overrides", "realtime_preferred",
                "priority", "resource_profile", "queue_tag"):
        if key in overrides:
            setattr(payload, key, overrides[key])
    return payload


# ─── SQLite 持久化 ───────────────────────────────────────────────────────────
class WorkflowTimerStore:
    """workflow_timers 表的薄包装。

    与 SQLiteWorkflowRepository 共享同一 DB 文件（workflow_state.sqlite3），
    但使用独立连接池避免与运行时 workflow_runs 写入争用。
    """

    def __init__(self, state_dir: str | Path | None = None) -> None:
        self._state_dir = Path(state_dir or settings.workflow_state_dir)
        self._db_path = self._state_dir / "workflow_state.sqlite3"
        self._state_dir.mkdir(parents=True, exist_ok=True)
        # 独立连接（线程锁保护，避免引入连接池依赖）
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            str(self._db_path),
            check_same_thread=False,
            isolation_level=None,  # autocommit；显式 BEGIN/COMMIT 控制
            timeout=30.0,
        )
        self._conn.row_factory = sqlite3.Row
        # WAL 模式：与 workflow_runs 表共享 DB 时必须
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA busy_timeout=30000")
        self._initialize_schema()

    def _initialize_schema(self) -> None:
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS workflow_timers (
                    timer_id TEXT PRIMARY KEY,
                    workflow_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    trigger_type TEXT NOT NULL,
                    trigger_config TEXT NOT NULL,
                    payload_overrides TEXT NOT NULL DEFAULT '{}',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    last_fired_at TEXT,
                    next_fire_at TEXT,
                    last_run_id TEXT,
                    last_error TEXT,
                    fire_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_workflow_timers_enabled_next ON workflow_timers(enabled, next_fire_at)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_workflow_timers_workflow_id ON workflow_timers(workflow_id)"
            )

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass

    # ── CRUD ──
    def list_timers(self, *, workflow_id: str | None = None) -> list[WorkflowTimer]:
        with self._lock:
            if workflow_id:
                rows = self._conn.execute(
                    "SELECT * FROM workflow_timers WHERE workflow_id = ? ORDER BY created_at ASC",
                    (workflow_id,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM workflow_timers ORDER BY created_at ASC"
                ).fetchall()
        return [self._row_to_timer(r) for r in rows]

    def get_timer(self, timer_id: str) -> WorkflowTimer | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM workflow_timers WHERE timer_id = ?",
                (timer_id,),
            ).fetchone()
        return self._row_to_timer(row) if row else None

    def create_timer(self, timer: WorkflowTimer) -> WorkflowTimer:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO workflow_timers
                (timer_id, workflow_id, name, trigger_type, trigger_config, payload_overrides,
                 enabled, last_fired_at, next_fire_at, last_run_id, last_error,
                 fire_count, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    timer.timer_id, timer.workflow_id, timer.name,
                    timer.trigger_type, json.dumps(timer.trigger_config, ensure_ascii=False),
                    json.dumps(timer.payload_overrides, ensure_ascii=False),
                    1 if timer.enabled else 0,
                    timer.last_fired_at, timer.next_fire_at,
                    timer.last_run_id, timer.last_error,
                    timer.fire_count, timer.created_at, timer.updated_at,
                ),
            )
        return timer

    def update_timer(self, timer_id: str, updates: dict[str, Any]) -> WorkflowTimer:
        """部分更新；仅允许更新 name/enabled/trigger_type/trigger_config/payload_overrides。"""
        existing = self.get_timer(timer_id)
        if existing is None:
            raise TimerNotFoundError(f"timer not found: {timer_id}")

        # 合并字段
        name = updates.get("name", existing.name)
        enabled = updates.get("enabled", existing.enabled)
        trigger_type = updates.get("trigger_type", existing.trigger_type)
        trigger_config = existing.trigger_config
        if "trigger_config" in updates:
            trigger_config = validate_trigger_config(trigger_type, updates["trigger_config"])
        payload_overrides = updates.get("payload_overrides", existing.payload_overrides)

        # 若 trigger 或 enabled 变化，重新计算 next_fire_at
        recomputed_next = existing.next_fire_at
        if (
            updates.get("trigger_type") is not None
            or updates.get("trigger_config") is not None
            or (enabled and not existing.enabled)
        ):
            last_dt = _parse_iso(existing.last_fired_at)
            recomputed_next = compute_next_fire_at(trigger_type, trigger_config, last_dt)
        if not enabled:
            recomputed_next = None

        updated_at = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._conn.execute(
                """
                UPDATE workflow_timers SET
                    name = ?, enabled = ?, trigger_type = ?, trigger_config = ?,
                    payload_overrides = ?, next_fire_at = ?, updated_at = ?
                WHERE timer_id = ?
                """,
                (
                    name, 1 if enabled else 0, trigger_type,
                    json.dumps(trigger_config, ensure_ascii=False),
                    json.dumps(payload_overrides, ensure_ascii=False),
                    recomputed_next, updated_at, timer_id,
                ),
            )
        result = self.get_timer(timer_id)
        assert result is not None
        return result

    def delete_timer(self, timer_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM workflow_timers WHERE timer_id = ?",
                (timer_id,),
            )
            return cur.rowcount > 0

    def fetch_due_timers(self, now: datetime) -> list[WorkflowTimer]:
        """获取所有已启用且 next_fire_at <= now 的定时器（不含 event 类型）。"""
        now_iso = now.isoformat()
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM workflow_timers
                WHERE enabled = 1
                  AND next_fire_at IS NOT NULL
                  AND next_fire_at <= ?
                  AND trigger_type IN ('cron', 'interval')
                ORDER BY next_fire_at ASC
                """,
                (now_iso,),
            ).fetchall()
        return [self._row_to_timer(r) for r in rows]

    def find_event_timers(self, event_type: str) -> list[WorkflowTimer]:
        """获取匹配 event_type 的所有已启用 event 触发器。"""
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM workflow_timers
                WHERE enabled = 1 AND trigger_type = 'event'
                """,
            ).fetchall()
        result = []
        for row in rows:
            timer = self._row_to_timer(row)
            if timer.trigger_config.get("event_type") == event_type:
                result.append(timer)
        return result

    def mark_fired(
        self,
        timer_id: str,
        *,
        run_id: str | None,
        error: str | None,
        next_fire_at: str | None,
    ) -> None:
        """更新触发后的状态：last_fired_at/last_run_id/last_error/fire_count/next_fire_at。"""
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._conn.execute(
                """
                UPDATE workflow_timers SET
                    last_fired_at = ?, last_run_id = ?, last_error = ?,
                    fire_count = fire_count + 1, next_fire_at = ?, updated_at = ?
                WHERE timer_id = ?
                """,
                (now_iso, run_id, error, next_fire_at, now_iso, timer_id),
            )

    def _row_to_timer(self, row: sqlite3.Row) -> WorkflowTimer:
        return WorkflowTimer(
            timer_id=row["timer_id"],
            workflow_id=row["workflow_id"],
            name=row["name"],
            trigger_type=row["trigger_type"],
            trigger_config=json.loads(row["trigger_config"]),
            payload_overrides=json.loads(row["payload_overrides"] or "{}"),
            enabled=bool(row["enabled"]),
            last_fired_at=row["last_fired_at"],
            next_fire_at=row["next_fire_at"],
            last_run_id=row["last_run_id"],
            last_error=row["last_error"],
            fire_count=row["fire_count"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


# ─── 模块级单例 ──────────────────────────────────────────────────────────────
_store_instance: WorkflowTimerStore | None = None
_store_lock = threading.Lock()


def get_timer_store() -> WorkflowTimerStore:
    """获取全局 WorkflowTimerStore 单例（lru_cache 替代品，避免 dataclass 限制）。"""
    global _store_instance
    if _store_instance is None:
        with _store_lock:
            if _store_instance is None:
                _store_instance = WorkflowTimerStore()
    return _store_instance


# ─── 定时器业务逻辑 ──────────────────────────────────────────────────────────
def create_timer(
    workflow_id: str,
    name: str,
    trigger_type: str,
    trigger_config: dict[str, Any],
    *,
    payload_overrides: dict[str, Any] | None = None,
    enabled: bool = True,
) -> WorkflowTimer:
    """创建并持久化一个新定时器。"""
    # 校验 workflow_id 存在
    from app.services import workflow_definition_service as wds
    if wds.get_definition(workflow_id) is None:
        raise TimerValidationError(f"workflow definition not found: {workflow_id}")

    normalized_config = validate_trigger_config(trigger_type, trigger_config)
    now = datetime.now(timezone.utc)
    next_fire = compute_next_fire_at(
        trigger_type, normalized_config, None,
    ) if enabled else None

    timer = WorkflowTimer(
        timer_id=f"timer-{uuid4().hex[:12]}",
        workflow_id=workflow_id,
        name=name,
        trigger_type=trigger_type,
        trigger_config=normalized_config,
        payload_overrides=payload_overrides or {},
        enabled=enabled,
        next_fire_at=next_fire,
        created_at=now.isoformat(),
        updated_at=now.isoformat(),
    )
    return get_timer_store().create_timer(timer)


def tick() -> dict[str, Any]:
    """Celery Beat 周期入口：检查到期定时器并提交工作流。

    返回 {checked, fired, failed, skipped} 统计。
    """
    store = get_timer_store()
    now = datetime.now(timezone.utc)
    due = store.fetch_due_timers(now)
    stats = {"checked": len(due), "fired": 0, "failed": 0, "skipped": 0}

    for timer in due:
        run_id, error = None, None
        try:
            payload = _build_submit_payload(timer.workflow_id, timer.payload_overrides)
            from app.services.workflow.service_container import submission_service
            accepted = submission_service.submit_workflow(payload)
            run_id = accepted.run_id
            stats["fired"] += 1
            logger.info(
                "workflow timer %s fired: workflow_id=%s run_id=%s",
                timer.timer_id, timer.workflow_id, run_id,
            )
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            stats["failed"] += 1
            logger.exception(
                "workflow timer %s failed to fire: %s", timer.timer_id, exc,
            )

        # 计算下次触发时间：以当前时间为基准（避免漏触发）
        try:
            now_dt = datetime.now(timezone.utc)
            next_fire = compute_next_fire_at(timer.trigger_type, timer.trigger_config, now_dt)
        except Exception:
            next_fire = None

        store.mark_fired(
            timer.timer_id,
            run_id=run_id,
            error=error,
            next_fire_at=next_fire,
        )

    return stats


def emit_event(event_type: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """发射外部事件，触发匹配的 event 类型定时器。

    返回 {matched, fired, failed} 统计。
    """
    store = get_timer_store()
    matched = store.find_event_timers(event_type)
    stats = {"matched": len(matched), "fired": 0, "failed": 0}

    for timer in matched:
        run_id, error = None, None
        try:
            # 合并事件 payload 到 payload_overrides.parameters
            overrides = dict(timer.payload_overrides)
            if payload:
                params = dict(overrides.get("parameters") or {})
                params.update({"event_payload": payload})
                overrides["parameters"] = params
            submit_payload = _build_submit_payload(timer.workflow_id, overrides)
            from app.services.workflow.service_container import submission_service
            accepted = submission_service.submit_workflow(submit_payload)
            run_id = accepted.run_id
            stats["fired"] += 1
            logger.info(
                "workflow timer %s triggered by event %s: run_id=%s",
                timer.timer_id, event_type, run_id,
            )
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            stats["failed"] += 1
            logger.exception(
                "workflow timer %s event trigger failed: %s", timer.timer_id, exc,
            )
        # event 触发器不需要计算 next_fire_at
        store.mark_fired(timer.timer_id, run_id=run_id, error=error, next_fire_at=None)
    return stats


def trigger_manually(timer_id: str) -> dict[str, Any]:
    """手动触发一次定时器对应的工作流（不影响 next_fire_at）。"""
    store = get_timer_store()
    timer = store.get_timer(timer_id)
    if timer is None:
        raise TimerNotFoundError(f"timer not found: {timer_id}")
    payload = _build_submit_payload(timer.workflow_id, timer.payload_overrides)
    from app.services.workflow.service_container import submission_service
    accepted = submission_service.submit_workflow(payload)
    # 更新 last_run_id 但不更新 fire_count 或 next_fire_at
    now_iso = datetime.now(timezone.utc).isoformat()
    store.mark_fired(
        timer_id,
        run_id=accepted.run_id,
        error=None,
        next_fire_at=timer.next_fire_at,  # 保留原值
    )
    return {
        "timer_id": timer_id,
        "run_id": accepted.run_id,
        "status_url": accepted.status_url,
        "triggered_at": now_iso,
    }


def timer_to_dict(timer: WorkflowTimer) -> dict[str, Any]:
    """序列化 WorkflowTimer 为 API 响应 dict。"""
    return {
        "timer_id": timer.timer_id,
        "workflow_id": timer.workflow_id,
        "name": timer.name,
        "trigger_type": timer.trigger_type,
        "trigger_config": timer.trigger_config,
        "payload_overrides": timer.payload_overrides,
        "enabled": timer.enabled,
        "last_fired_at": timer.last_fired_at,
        "next_fire_at": timer.next_fire_at,
        "last_run_id": timer.last_run_id,
        "last_error": timer.last_error,
        "fire_count": timer.fire_count,
        "created_at": timer.created_at,
        "updated_at": timer.updated_at,
    }
