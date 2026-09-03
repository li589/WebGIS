"""僵尸工作流任务回收（2026-08-25「任务长期卡排队中」根治）。

根因：Redis/Docker 重启或 worker 停机时，Celery 队列中的任务丢失，
但 run 状态已写入 accepted/queued——没有任何组件会再推进它，前端
永远显示「排队中」。本任务周期扫描 accepted/queued 且超时无任何
状态推进的 run，CAS 标记为 failed（消息提示可重试），由用户侧
retry 或前端自动重试恢复。

超时阈值（settings.workflow_stuck_reclaim_seconds，默认 1800s =
30 分钟）：排队繁忙是正常的（download/heavy 队列长任务），仅在
「无任何事件推进」超过阈值才判定为派发丢失。

活动时钟 = max(run.updated_at, 最近一条 workflow_events.created_at)，
与 fail_stuck_running_workflows 一致：中途进度常只写 events、不 bump
updated_at。

CAS 使用 max_retries=1：禁止在冲突时把 expected 从 queued 刷新为
running 后再强写 failed（默认 save_run_cas 的 refresh 语义会误杀
「刚被 worker 接手」的长任务，例如 omega_sf_fenkuai）。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from app.core.celery_app import celery_app
from app.core.config import settings
from app.services.workflow_repository import (
    ConcurrentModificationError,
    SQLiteWorkflowRepository,
)
from shared.contracts.api_contracts import ExecutionStatus

logger = logging.getLogger(__name__)

# accepted/queued 期间无事件推进的回收判定状态集
_STUCK_STATUSES = {"accepted", "queued"}


def _last_activity_at(
    repository: SQLiteWorkflowRepository,
    run_id: str,
    updated_at: datetime,
) -> datetime:
    """活动时钟：run 行更新与最新事件取较晚者。"""
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=UTC)
    last_event_at = repository.get_latest_event_created_at(run_id)
    if last_event_at is not None and last_event_at > updated_at:
        return last_event_at
    return updated_at


@celery_app.task(name="app.tasks.workflow_reclaim_tasks.reclaim_stuck_workflow_runs")
def reclaim_stuck_workflow_runs() -> dict[str, object]:
    """扫描并回收卡死的 accepted/queued run（beat 周期触发）。"""
    repository = SQLiteWorkflowRepository()
    timeout_s = int(getattr(settings, "workflow_stuck_reclaim_seconds", 1800) or 1800)
    now = datetime.now(UTC)
    reclaimed: list[str] = []
    skipped = 0

    for run in repository.list_runs():
        if run.status not in _STUCK_STATUSES:
            continue
        last_activity = _last_activity_at(repository, run.run_id, run.updated_at)
        idle_s = (now - last_activity).total_seconds()
        if idle_s <= timeout_s:
            skipped += 1
            continue

        # CAS：仅当状态仍是读取时的 accepted/queued 才落 failed。
        # max_retries=1：与恰好恢复消费、已推进到 running 的 worker 竞争时
        # 必须失败并跳过——禁止 refresh expected 后覆盖 running。
        try:
            expected = ExecutionStatus(run.status)
            run.status = ExecutionStatus.failed
            run.progress = 100
            run.message = (
                "任务派发丢失（broker 重启或 worker 停机超时），"
                "已自动回收——请点击重试恢复。"
            )
            run.updated_at = now
            if repository.save_run_cas(
                run, expected_status=expected, max_retries=1
            ):
                reclaimed.append(run.run_id)
                logger.warning(
                    "Reclaimed stuck workflow run %s (idle %.0fs > %ds)",
                    run.run_id,
                    idle_s,
                    timeout_s,
                )
            else:
                skipped += 1
        except ConcurrentModificationError:
            logger.debug(
                "Skip reclaim run %s (status advanced past accepted/queued)",
                run.run_id,
            )
            skipped += 1
        except Exception:
            # 单个 run 回收失败不阻断其余
            logger.debug("Skip reclaim run %s (error)", run.run_id, exc_info=True)
            skipped += 1

    if reclaimed:
        logger.warning(
            "Zombie run reclaim: %d reclaimed, %d still within timeout",
            len(reclaimed),
            skipped,
        )
    return {"reclaimed": reclaimed, "skipped_active": skipped}
