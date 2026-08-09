"""工作流定时器服务

为工作流模块提供自动运行能力，支持三种触发类型：
- cron: 5 字段 cron 表达式（minute hour day month weekday），按 Asia/Shanghai 墙钟解释
- interval: 固定间隔（秒）
- event: 外部事件触发（通过 emit_event 接口）

存储使用与 workflow_runs 相同的 SQLite 数据库（workflow_state.sqlite3），
表名 workflow_timers。Celery Beat 每分钟调用 tick() 检查到期定时器并提交工作流。

设计要点：
- 旧数据兼容：表通过 _initialize_schema 创建（当前无额外迁移步骤）
- cron 解析自实现（无外部依赖），支持 *、*/N、N、N,M、N-M 五种语法
- day-of-month 与 day-of-week 同时为受限值时按 AND 匹配（非 Vixie OR）
- 下次触发时间存 UTC ISO；cron / 日期模板按 Asia/Shanghai 墙钟求值
- tick 用乐观 claim 防止 FastAPI /tick 与 Beat 双触发
- 僵死 CLAIMED 哨兵按 TTL（默认 5 分钟）在 tick 开头回收，避免进程崩溃后定时器永久停摆
- 提交失败不影响下次触发，错误记录到 last_error 字段
- 事件触发器立即响应 emit_event 调用（同步提交）
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, UTC
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.core.config import settings

logger = logging.getLogger(__name__)

# Cron / 日期模板墙钟时区（存储仍为 UTC ISO）
TIMER_TZ = ZoneInfo("Asia/Shanghai")

# claim 后若进程在 mark_fired 前崩溃，CLAIMED 哨兵超过此时长则回收为立即到期
CLAIM_TTL_SECONDS = 300


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
# 语义：hour/minute 按 Asia/Shanghai 墙钟；DOM 与 DOW 同时受限时为 AND。
_FIELD_RANGES = [
    (0, 59),  # minute
    (0, 23),  # hour
    (1, 31),  # day of month
    (1, 12),  # month
    (0, 6),  # day of week (0=Sunday)
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


def _ensure_aware_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def next_cron_time(cron_expr: str, after: datetime) -> datetime:
    """计算 cron 表达式在 after 之后的下一次触发时间（返回 UTC aware）。

    表达式中的 hour/minute/DOM/DOW 按 Asia/Shanghai 墙钟解释。
    逐日扫描月/日/星期匹配，匹配日内在时/分组合中查找最早时间。
    最多扫描 8 年（覆盖 Gregorian 闰年最大间隔）。
    """
    parsed = parse_cron(cron_expr)
    after_utc = _ensure_aware_utc(after)
    local_after = after_utc.astimezone(TIMER_TZ)
    candidate = local_after.replace(second=0, microsecond=0) + timedelta(minutes=1)
    # Python weekday: Monday=0 ... Sunday=6；cron weekday: Sunday=0 ... Saturday=6
    max_days = 366 * 8
    for _ in range(max_days):
        cron_wd = (candidate.weekday() + 1) % 7
        if (
            candidate.month in parsed["month"]
            and candidate.day in parsed["day_of_month"]
            and cron_wd in parsed["day_of_week"]
        ):
            for hour in sorted(parsed["hour"]):
                for minute in sorted(parsed["minute"]):
                    if (hour, minute) >= (candidate.hour, candidate.minute):
                        local_hit = candidate.replace(
                            hour=hour, minute=minute, second=0, microsecond=0
                        )
                        return local_hit.astimezone(UTC)
        candidate = (candidate + timedelta(days=1)).replace(hour=0, minute=0)
    raise TimerValidationError(f"no next fire time found for cron: {cron_expr}")


# ─── 触发器配置校验 ──────────────────────────────────────────────────────────
def validate_trigger_config(
    trigger_type: str, config: dict[str, Any]
) -> dict[str, Any]:
    """校验并规范化触发器配置。返回规范化后的 config。"""
    if trigger_type == "cron":
        expr = config.get("cron")
        if not isinstance(expr, str) or not expr.strip():
            raise TimerValidationError("cron trigger requires 'cron' string field")
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
            raise TimerValidationError(
                "event trigger requires 'event_type' string field"
            )
        return {"event_type": event_type.strip()}
    raise TimerValidationError(
        f"unknown trigger_type: {trigger_type!r} (expected: cron | interval | event)"
    )


def compute_next_fire_at(
    trigger_type: str,
    config: dict[str, Any],
    last_fired_at: datetime | None,
    *,
    now: datetime | None = None,
) -> str | None:
    """计算下次触发时间（ISO 8601 UTC）。event 类型返回 None（仅事件触发）。

    interval：若 last+seconds 已过去，clamp 到 now+seconds，避免停机后每分钟连打。
    """
    now_utc = _ensure_aware_utc(now or datetime.now(UTC))
    if trigger_type == "cron":
        base = _ensure_aware_utc(last_fired_at) if last_fired_at else now_utc
        return next_cron_time(config["cron"], base).isoformat()
    if trigger_type == "interval":
        seconds = int(config["seconds"])
        base = _ensure_aware_utc(last_fired_at) if last_fired_at else now_utc
        next_dt = base + timedelta(seconds=seconds)
        if next_dt <= now_utc:
            next_dt = now_utc + timedelta(seconds=seconds)
        return next_dt.astimezone(UTC).isoformat()
    return None  # event


# ─── 工作流提交辅助 ──────────────────────────────────────────────────────────
def _definition_graph_body(definition: dict[str, Any]) -> dict[str, Any]:
    """提取可提交的图定义体（保留 nodes/links 等，去掉仅元数据用途的 _meta）。"""
    return {k: v for k, v in definition.items() if k != "_meta"}


def _build_submit_payload(
    workflow_id: str,
    overrides: dict[str, Any],
) -> Any:
    """根据 workflow_id 加载定义并合并 overrides，构造 WorkflowSubmitRequest。

    按 ``_meta.engine`` 注入引擎请求，避免空壳 analysis run：
    - python_provider → algorithm_request.workflow_name / workflow_definition
    - weather → weather_request.workflow_id (+ workflow 图)
    - gee → gee_request.workflow_id (+ workflow 图)
    overrides 中显式提供的 engine request / layer_id 等仍优先生效。
    """
    from app.services import workflow_definition_service as wds
    from shared.contracts.api_contracts import (
        AlgorithmWorkflowRequest,
        GeeWorkflowRequest,
        WeatherWorkflowRequest,
        WorkflowCommandType,
        WorkflowSubmitRequest,
    )

    definition = wds.get_definition(workflow_id)
    if definition is None:
        raise TimerValidationError(f"workflow definition not found: {workflow_id}")

    meta = definition.get("_meta") if isinstance(definition.get("_meta"), dict) else {}
    extra = definition.get("extra") if isinstance(definition.get("extra"), dict) else {}
    engine = str(meta.get("engine") or "common")

    command_str = extra.get("default_command") or "analysis"
    try:
        command_type = WorkflowCommandType(command_str)
    except ValueError:
        command_type = WorkflowCommandType.analysis

    layer_id = (
        overrides.get("layer_id")
        or extra.get("default_layer_id")
        or meta.get("linked_layer_id")
    )
    parameters = dict(extra.get("default_parameters") or {})
    parameters.update(overrides.get("parameters") or {})
    parameters = resolve_date_templates(parameters)  # type: ignore[assignment]

    payload = WorkflowSubmitRequest(
        command_type=command_type,
        command_label=overrides.get("command_label") or f"timer:{workflow_id}",
        layer_id=layer_id,
        parameters=parameters,
    )

    graph_body = _definition_graph_body(definition)
    seed_algo_params = _extract_seed_algorithm_params(definition)

    if "algorithm_request" not in overrides and engine in (
        "python_provider",
        "common",
    ):
        algo_params = dict(seed_algo_params)
        if isinstance(parameters, dict):
            algo_params.update(parameters)
        # workflow_name 走种子路径；同时附带图定义供 flatten / 画布执行
        payload.algorithm_request = AlgorithmWorkflowRequest(
            workflow_name=workflow_id,
            workflow_definition=graph_body,
            algorithm_params=algo_params,
        )
    if "weather_request" not in overrides and engine == "weather":
        payload.weather_request = WeatherWorkflowRequest(
            workflow_id=workflow_id,
            workflow=graph_body,
            layer_id=layer_id,
        )
    if "gee_request" not in overrides and engine == "gee":
        payload.gee_request = GeeWorkflowRequest(
            workflow_id=workflow_id,
            workflow=graph_body,
        )

    for key in (
        "time_range",
        "spatial_filter",
        "gee_request",
        "weather_request",
        "algorithm_request",
        "config_overrides",
        "realtime_preferred",
        "priority",
        "resource_profile",
        "queue_tag",
    ):
        if key in overrides:
            setattr(payload, key, resolve_date_templates(overrides[key]))
    return payload


def _extract_seed_algorithm_params(definition: dict[str, Any]) -> dict[str, Any]:
    """从种子 module/* 节点 properties.algorithm_params 提取默认参数。"""
    for node in definition.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        node_type = node.get("type") or node.get("node_type") or ""
        if not str(node_type).startswith("module/"):
            continue
        props = node.get("properties") or {}
        params = props.get("algorithm_params")
        if isinstance(params, dict) and params:
            return dict(params)
    return {}


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
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            str(self._db_path),
            check_same_thread=False,
            isolation_level=None,  # autocommit；显式 BEGIN/COMMIT 控制
            timeout=30.0,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA busy_timeout=30000")
        try:
            from app.services import spatialite_loader

            spatialite_loader.load_into(self._conn)
        except Exception:
            logger.debug(
                "SpatiaLite load skipped for workflow_timers connection",
                exc_info=True,
            )
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
                    timer.timer_id,
                    timer.workflow_id,
                    timer.name,
                    timer.trigger_type,
                    json.dumps(timer.trigger_config, ensure_ascii=False),
                    json.dumps(timer.payload_overrides, ensure_ascii=False),
                    1 if timer.enabled else 0,
                    timer.last_fired_at,
                    timer.next_fire_at,
                    timer.last_run_id,
                    timer.last_error,
                    timer.fire_count,
                    timer.created_at,
                    timer.updated_at,
                ),
            )
        return timer

    def update_timer(self, timer_id: str, updates: dict[str, Any]) -> WorkflowTimer:
        """部分更新；仅允许更新 name/enabled/trigger_type/trigger_config/payload_overrides。"""
        existing = self.get_timer(timer_id)
        if existing is None:
            raise TimerNotFoundError(f"timer not found: {timer_id}")

        name = updates.get("name", existing.name)
        enabled = updates.get("enabled", existing.enabled)
        trigger_type = updates.get("trigger_type", existing.trigger_type)
        type_changed = (
            "trigger_type" in updates
            and updates["trigger_type"] != existing.trigger_type
        )
        if type_changed and "trigger_config" not in updates:
            raise TimerValidationError(
                "changing trigger_type requires a matching trigger_config"
            )

        trigger_config = existing.trigger_config
        if "trigger_config" in updates or type_changed:
            raw_config = updates.get("trigger_config", existing.trigger_config)
            if not isinstance(raw_config, dict):
                raise TimerValidationError("trigger_config must be an object")
            trigger_config = validate_trigger_config(trigger_type, raw_config)

        payload_overrides = updates.get("payload_overrides", existing.payload_overrides)

        recomputed_next = existing.next_fire_at
        if (
            updates.get("trigger_type") is not None
            or updates.get("trigger_config") is not None
            or (enabled and not existing.enabled)
        ):
            last_dt = _parse_iso(existing.last_fired_at)
            recomputed_next = compute_next_fire_at(
                trigger_type, trigger_config, last_dt
            )
        if not enabled:
            recomputed_next = None

        updated_at = datetime.now(UTC).isoformat()
        with self._lock:
            self._conn.execute(
                """
                UPDATE workflow_timers SET
                    name = ?, enabled = ?, trigger_type = ?, trigger_config = ?,
                    payload_overrides = ?, next_fire_at = ?, updated_at = ?
                WHERE timer_id = ?
                """,
                (
                    name,
                    1 if enabled else 0,
                    trigger_type,
                    json.dumps(trigger_config, ensure_ascii=False),
                    json.dumps(payload_overrides, ensure_ascii=False),
                    recomputed_next,
                    updated_at,
                    timer_id,
                ),
            )
        result = self.get_timer(timer_id)
        if result is None:
            raise RuntimeError(f"timer disappeared after update: {timer_id}")
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
        now_iso = _ensure_aware_utc(now).isoformat()
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM workflow_timers
                WHERE enabled = 1
                  AND next_fire_at IS NOT NULL
                  AND next_fire_at NOT LIKE 'CLAIMED:%'
                  AND next_fire_at <= ?
                  AND trigger_type IN ('cron', 'interval')
                ORDER BY next_fire_at ASC
                """,
                (now_iso,),
            ).fetchall()
        return [self._row_to_timer(r) for r in rows]

    def reclaim_stale_claims(
        self, now: datetime, *, ttl_seconds: int = CLAIM_TTL_SECONDS
    ) -> int:
        """回收超时的 CLAIMED 哨兵，避免 claim 后崩溃导致定时器永久停摆。

        依据 claim 时写入的 ``updated_at``：若 ``now - updated_at >= ttl``，
        将 ``next_fire_at`` 重置为 ``now``（立即再次进入 due）。
        """
        now_utc = _ensure_aware_utc(now)
        now_iso = now_utc.isoformat()
        cutoff = (now_utc - timedelta(seconds=max(1, ttl_seconds))).isoformat()
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                cur = self._conn.execute(
                    """
                    UPDATE workflow_timers
                    SET next_fire_at = ?, updated_at = ?
                    WHERE enabled = 1
                      AND next_fire_at LIKE 'CLAIMED:%'
                      AND updated_at <= ?
                      AND trigger_type IN ('cron', 'interval')
                    """,
                    (now_iso, now_iso, cutoff),
                )
                self._conn.execute("COMMIT")
            except Exception:
                try:
                    self._conn.execute("ROLLBACK")
                except Exception:
                    pass
                raise
        reclaimed = int(cur.rowcount or 0)
        if reclaimed:
            logger.warning(
                "reclaimed %s stale CLAIMED workflow timer(s) (ttl=%ss)",
                reclaimed,
                ttl_seconds,
            )
        return reclaimed

    def claim_due_timers(self, now: datetime) -> tuple[list[WorkflowTimer], int]:
        """乐观 claim 到期定时器，防止跨进程双触发。

        Returns:
            (claimed, skipped): skipped 为因 next_fire_at 已变而抢锁失败的数量。
        """
        now_utc = _ensure_aware_utc(now)
        now_iso = now_utc.isoformat()
        candidates = self.fetch_due_timers(now_utc)
        claimed: list[WorkflowTimer] = []
        skipped = 0
        for timer in candidates:
            expected_next = timer.next_fire_at
            claim_token = f"CLAIMED:{now_iso}:{uuid4().hex[:8]}"
            with self._lock:
                self._conn.execute("BEGIN IMMEDIATE")
                try:
                    cur = self._conn.execute(
                        """
                        UPDATE workflow_timers
                        SET next_fire_at = ?, updated_at = ?
                        WHERE timer_id = ?
                          AND enabled = 1
                          AND next_fire_at = ?
                          AND trigger_type IN ('cron', 'interval')
                        """,
                        (claim_token, now_iso, timer.timer_id, expected_next),
                    )
                    self._conn.execute("COMMIT")
                except Exception:
                    try:
                        self._conn.execute("ROLLBACK")
                    except Exception:
                        pass
                    raise
            if cur.rowcount == 1:
                claimed.append(timer)
            else:
                skipped += 1
        return claimed, skipped

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
        now_iso = datetime.now(UTC).isoformat()
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

    def update_last_run(
        self,
        timer_id: str,
        *,
        run_id: str | None,
        error: str | None,
    ) -> None:
        """仅更新 last_run_id/last_error，不影响 fire_count/last_fired_at/next_fire_at。

        用于手动触发场景：记录最新 run_id 但不污染自动触发的统计数据和调度基准。
        """
        now_iso = datetime.now(UTC).isoformat()
        with self._lock:
            self._conn.execute(
                """
                UPDATE workflow_timers SET
                    last_run_id = ?, last_error = ?, updated_at = ?
                WHERE timer_id = ?
                """,
                (run_id, error, now_iso, timer_id),
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
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return _ensure_aware_utc(dt)
    except ValueError:
        return None


# ─── 模块级单例 ──────────────────────────────────────────────────────────────
_store_instance: WorkflowTimerStore | None = None
_store_lock = threading.Lock()


def get_timer_store() -> WorkflowTimerStore:
    """获取全局 WorkflowTimerStore 单例。"""
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
    from app.services import workflow_definition_service as wds

    if wds.get_definition(workflow_id) is None:
        raise TimerValidationError(f"workflow definition not found: {workflow_id}")

    normalized_config = validate_trigger_config(trigger_type, trigger_config)
    now = datetime.now(UTC)
    next_fire = (
        compute_next_fire_at(
            trigger_type,
            normalized_config,
            None,
            now=now,
        )
        if enabled
        else None
    )

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

    返回 {checked, fired, failed, skipped, reclaimed} 统计。
    skipped = claim 竞争失败数量；reclaimed = 超时 CLAIMED 回收数量。
    """
    store = get_timer_store()
    now = datetime.now(UTC)
    reclaimed = store.reclaim_stale_claims(now)
    claimed, skipped = store.claim_due_timers(now)
    stats = {
        "checked": len(claimed) + skipped,
        "fired": 0,
        "failed": 0,
        "skipped": skipped,
        "reclaimed": reclaimed,
    }

    for timer in claimed:
        run_id, error = None, None
        try:
            payload = _build_submit_payload(timer.workflow_id, timer.payload_overrides)
            from app.services.workflow.service_container import submission_service

            accepted = submission_service.submit_workflow(payload)
            run_id = accepted.run_id
            stats["fired"] += 1
            logger.info(
                "workflow timer %s fired: workflow_id=%s run_id=%s",
                timer.timer_id,
                timer.workflow_id,
                run_id,
            )
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            stats["failed"] += 1
            logger.exception(
                "workflow timer %s failed to fire: %s",
                timer.timer_id,
                exc,
            )

        try:
            now_dt = datetime.now(UTC)
            next_fire = compute_next_fire_at(
                timer.trigger_type, timer.trigger_config, now_dt, now=now_dt
            )
        except Exception:
            next_fire = None

        store.mark_fired(
            timer.timer_id,
            run_id=run_id,
            error=error,
            next_fire_at=next_fire,
        )

    return stats


def emit_event(
    event_type: str, payload: dict[str, Any] | None = None
) -> dict[str, Any]:
    """发射外部事件，触发匹配的 event 类型定时器。

    返回 {matched, fired, failed} 统计。
    """
    store = get_timer_store()
    matched = store.find_event_timers(event_type)
    stats = {"matched": len(matched), "fired": 0, "failed": 0}

    for timer in matched:
        run_id, error = None, None
        try:
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
                timer.timer_id,
                event_type,
                run_id,
            )
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            stats["failed"] += 1
            logger.exception(
                "workflow timer %s event trigger failed: %s",
                timer.timer_id,
                exc,
            )
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
    now_iso = datetime.now(UTC).isoformat()
    store.update_last_run(
        timer_id,
        run_id=accepted.run_id,
        error=None,
    )
    return {
        "timer_id": timer_id,
        "run_id": accepted.run_id,
        "status_url": accepted.status_url,
        "triggered_at": now_iso,
    }


def preview_cron(cron_expr: str, count: int = 5) -> list[str]:
    """计算 cron 表达式接下来 count 次触发时间（ISO 8601 UTC）。

    墙钟语义为 Asia/Shanghai；用于前端实时预览。
    """
    if count < 1 or count > 20:
        count = 5
    expr = cron_expr.strip()
    parse_cron(expr)
    results: list[str] = []
    candidate = datetime.now(UTC)
    for _ in range(count):
        nxt = next_cron_time(expr, candidate)
        results.append(nxt.isoformat())
        candidate = nxt
    return results


# ─── 动态日期模板解析 ──────────────────────────────────────────────────────────


def resolve_date_templates(value: Any) -> Any:
    """递归解析值中的动态日期模板占位符（按 Asia/Shanghai 日历日）。

    支持的模板（在触发时求值，确保使用最新日期）：
      {{today}}             → 当前日期 YYYYMMDD
      {{yesterday}}         → 昨日 YYYYMMDD
      {{tomorrow}}          → 明日 YYYYMMDD
      {{last_7_days_start}} → 7 天前 YYYYMMDD
      {{last_7_days_end}}   → 昨日 YYYYMMDD
      {{last_30_days_start}}→ 30 天前 YYYYMMDD
      {{last_30_days_end}}  → 昨日 YYYYMMDD
      {{this_month_start}}  → 本月 1 日 YYYYMMDD
      {{this_month_end}}    → 今日 YYYYMMDD
      {{last_month_start}}  → 上月 1 日 YYYYMMDD
      {{last_month_end}}    → 上月最后一天 YYYYMMDD
      {{this_year_start}}   → 本年 1 月 1 日 YYYYMMDD
      {{this_year_end}}     → 今日 YYYYMMDD
    """
    if isinstance(value, str):
        return _resolve_string_templates(value)
    if isinstance(value, dict):
        return {k: resolve_date_templates(v) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_date_templates(item) for item in value]
    return value


def _resolve_string_templates(s: str) -> Any:
    """解析字符串中的 {{...}} 占位符。"""
    if "{{" not in s:
        return s

    now = datetime.now(UTC).astimezone(TIMER_TZ)
    today = now.strftime("%Y%m%d")
    yesterday = (now - timedelta(days=1)).strftime("%Y%m%d")
    tomorrow = (now + timedelta(days=1)).strftime("%Y%m%d")

    first_of_month = now.replace(day=1)
    if now.month == 1:
        last_month_first = first_of_month.replace(year=now.year - 1, month=12)
    else:
        last_month_first = first_of_month.replace(month=now.month - 1)
    last_month_last = first_of_month - timedelta(days=1)

    first_of_year = now.replace(month=1, day=1)

    templates: dict[str, str] = {
        "today": today,
        "yesterday": yesterday,
        "tomorrow": tomorrow,
        "last_7_days_start": (now - timedelta(days=7)).strftime("%Y%m%d"),
        "last_7_days_end": yesterday,
        "last_30_days_start": (now - timedelta(days=30)).strftime("%Y%m%d"),
        "last_30_days_end": yesterday,
        "this_month_start": first_of_month.strftime("%Y%m%d"),
        "this_month_end": today,
        "last_month_start": last_month_first.strftime("%Y%m%d"),
        "last_month_end": last_month_last.strftime("%Y%m%d"),
        "this_year_start": first_of_year.strftime("%Y%m%d"),
        "this_year_end": today,
    }

    result = s
    for key, val in templates.items():
        result = result.replace("{{" + key + "}}", val)

    stripped = result.strip()
    if stripped.isdigit() and len(stripped) == 8:
        try:
            return int(stripped)
        except ValueError:
            pass

    return result


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
