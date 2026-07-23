"""
天气工作流生命周期管理器

管理天气工作流的自动运行/停止，支持视口优先级调度。
确保每类图层只有一个活跃工作流，支持自动替换。
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Callable, Awaitable
import asyncio
import logging
import threading

logger = logging.getLogger(__name__)


class WorkflowPriority(Enum):
    """工作流优先级枚举"""

    VIEWPORT = 0  # 视口区域，优先处理
    SURROUNDING = 1  # 外围区域，异步处理
    BACKGROUND = 2  # 后台任务，可被抢占


class WorkflowState(Enum):
    """工作流状态枚举"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ManagedWorkflow:
    """管理工作流对象"""

    workflow_id: str
    layer_id: str
    priority: WorkflowPriority
    state: WorkflowState
    created_at: datetime
    run_id: Optional[str] = None
    bbox: Optional[dict] = None  # 空间范围 {"min_lng", "max_lng", "min_lat", "max_lat"}
    metadata: dict = field(default_factory=dict)
    cancel_callback: Optional[Callable[[], Awaitable[None]]] = None


class WorkflowLifecycleManager:
    """天气工作流生命周期管理器

    职责：
    1. 维护 layer_id → 活跃工作流映射（每类图层只允许一个活跃工作流）
    2. 支持优先级调度（viewport > surrounding > background）
    3. 自动取消旧工作流，替换为新工作流
    4. 处理视口变化触发的更新

    使用线程安全的方式管理工作流，支持同步和异步调用。
    """

    def __init__(self) -> None:
        # layer_id → ManagedWorkflow
        self._active_workflows: dict[str, ManagedWorkflow] = {}
        # 优先级队列存储待处理的工作流
        self._pending_workflows: list[tuple[int, ManagedWorkflow]] = []
        self._lock = threading.RLock()
        self._async_lock: Optional[asyncio.Lock] = None

    def _get_async_lock(self) -> asyncio.Lock:
        """获取或创建异步锁（延迟初始化避免循环导入）"""
        if self._async_lock is None:
            self._async_lock = asyncio.Lock()
        return self._async_lock

    def submit_workflow(
        self,
        *,
        layer_id: str,
        workflow_id: str,
        priority: WorkflowPriority,
        bbox: Optional[dict] = None,
        metadata: Optional[dict] = None,
        cancel_callback: Optional[Callable[[], Awaitable[None]]] = None,
    ) -> str:
        """提交工作流，自动处理旧工作流替换（同步版本）

        Args:
            layer_id: 图层 ID
            workflow_id: 工作流 ID
            priority: 优先级
            bbox: 空间范围
            metadata: 元数据
            cancel_callback: 取消回调函数

        Returns:
            新工作流的 workflow_id
        """
        with self._lock:
            # 检查是否已有该 layer_id 的活跃工作流
            existing = self._active_workflows.get(layer_id)
            if existing and existing.state == WorkflowState.RUNNING:
                # 取消旧工作流
                self._cancel_workflow_sync(existing)
                logger.info(
                    f"[WorkflowLifecycleManager] Cancelled old workflow {existing.workflow_id} for layer {layer_id}"
                )

            # 创建新工作流
            workflow = ManagedWorkflow(
                workflow_id=workflow_id,
                layer_id=layer_id,
                priority=priority,
                state=WorkflowState.PENDING,
                created_at=datetime.now(timezone.utc),
                bbox=bbox,
                metadata=metadata or {},
                cancel_callback=cancel_callback,
            )
            self._active_workflows[layer_id] = workflow

            # 加入优先级队列
            self._pending_workflows.append((priority.value, workflow))
            self._pending_workflows.sort(key=lambda x: x[0])

            logger.info(
                f"[WorkflowLifecycleManager] Submitted workflow {workflow_id} for layer {layer_id} with priority {priority.name}"
            )
            return workflow_id

    async def submit_workflow_async(
        self,
        *,
        layer_id: str,
        workflow_id: str,
        priority: WorkflowPriority,
        bbox: Optional[dict] = None,
        metadata: Optional[dict] = None,
        cancel_callback: Optional[Callable[[], Awaitable[None]]] = None,
    ) -> str:
        """提交工作流，自动处理旧工作流替换（异步版本）"""
        async with self._get_async_lock():
            # 检查是否已有该 layer_id 的活跃工作流
            existing = self._active_workflows.get(layer_id)
            if existing and existing.state == WorkflowState.RUNNING:
                # 取消旧工作流
                await self._cancel_workflow_async(existing)
                logger.info(
                    f"[WorkflowLifecycleManager] Cancelled old workflow {existing.workflow_id} for layer {layer_id}"
                )

            # 创建新工作流
            workflow = ManagedWorkflow(
                workflow_id=workflow_id,
                layer_id=layer_id,
                priority=priority,
                state=WorkflowState.PENDING,
                created_at=datetime.now(timezone.utc),
                bbox=bbox,
                metadata=metadata or {},
                cancel_callback=cancel_callback,
            )
            self._active_workflows[layer_id] = workflow

            # 加入优先级队列
            self._pending_workflows.append((priority.value, workflow))
            self._pending_workflows.sort(key=lambda x: x[0])

            logger.info(
                f"[WorkflowLifecycleManager] Submitted workflow {workflow_id} for layer {layer_id} with priority {priority.name}"
            )
            return workflow_id

    def update_workflow_state(
        self,
        layer_id: str,
        state: WorkflowState,
        run_id: Optional[str] = None,
    ) -> bool:
        """更新工作流状态（同步版本）

        Args:
            layer_id: 图层 ID
            state: 新状态
            run_id: 运行 ID

        Returns:
            是否更新成功
        """
        with self._lock:
            workflow = self._active_workflows.get(layer_id)
            if workflow:
                old_state = workflow.state
                workflow.state = state
                if run_id:
                    workflow.run_id = run_id

                logger.info(
                    f"[WorkflowLifecycleManager] Updated workflow {workflow.workflow_id} state: {old_state.value} -> {state.value}"
                )

                # 如果工作流已完成或失败，从活跃列表移除（保留 cancel 状态以便调试）
                if state in (
                    WorkflowState.COMPLETED,
                    WorkflowState.FAILED,
                    WorkflowState.CANCELLED,
                ):
                    # 从待处理队列移除
                    self._pending_workflows = [
                        (p, w)
                        for p, w in self._pending_workflows
                        if w.workflow_id != workflow.workflow_id
                    ]

                return True
            return False

    async def update_workflow_state_async(
        self,
        layer_id: str,
        state: WorkflowState,
        run_id: Optional[str] = None,
    ) -> bool:
        """更新工作流状态（异步版本）"""
        async with self._get_async_lock():
            return self.update_workflow_state(layer_id, state, run_id)

    def _cancel_workflow_sync(self, workflow: ManagedWorkflow) -> None:
        """同步取消工作流"""
        workflow.state = WorkflowState.CANCELLED

        # 从待处理队列移除
        self._pending_workflows = [
            (p, w)
            for p, w in self._pending_workflows
            if w.workflow_id != workflow.workflow_id
        ]

        # 调用取消回调
        if workflow.cancel_callback:
            try:
                # 尝试调用异步回调
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(workflow.cancel_callback())
                else:
                    loop.run_until_complete(workflow.cancel_callback())
            except Exception as e:
                # Sprint 3.5: 编程 bug 必须向上传播；cancel_callback 中的网络/API 失败降级为 warning。
                if isinstance(
                    e, (AttributeError, NameError, TypeError, ImportError, SyntaxError)
                ):
                    raise
                logger.warning(
                    f"[WorkflowLifecycleManager] Cancel callback failed: {e}"
                )

    async def _cancel_workflow_async(self, workflow: ManagedWorkflow) -> None:
        """异步取消工作流"""
        workflow.state = WorkflowState.CANCELLED

        # 从待处理队列移除
        self._pending_workflows = [
            (p, w)
            for p, w in self._pending_workflows
            if w.workflow_id != workflow.workflow_id
        ]

        # 调用取消回调
        if workflow.cancel_callback:
            try:
                await workflow.cancel_callback()
            except Exception as e:
                # Sprint 3.5: 编程 bug 必须向上传播；cancel_callback 中的网络/API 失败降级为 warning。
                if isinstance(
                    e, (AttributeError, NameError, TypeError, ImportError, SyntaxError)
                ):
                    raise
                logger.warning(
                    f"[WorkflowLifecycleManager] Cancel callback failed: {e}"
                )

    def cancel_workflow(self, layer_id: str) -> bool:
        """取消指定图层的工作流（同步版本）"""
        with self._lock:
            workflow = self._active_workflows.get(layer_id)
            if workflow:
                self._cancel_workflow_sync(workflow)
                logger.info(
                    f"[WorkflowLifecycleManager] Cancelled workflow {workflow.workflow_id} for layer {layer_id}"
                )
                return True
            return False

    async def cancel_workflow_async(self, layer_id: str) -> bool:
        """取消指定图层的工作流（异步版本）"""
        async with self._get_async_lock():
            workflow = self._active_workflows.get(layer_id)
            if workflow:
                await self._cancel_workflow_async(workflow)
                logger.info(
                    f"[WorkflowLifecycleManager] Cancelled workflow {workflow.workflow_id} for layer {layer_id}"
                )
                return True
            return False

    def get_active_workflow(self, layer_id: str) -> Optional[ManagedWorkflow]:
        """获取活跃工作流"""
        with self._lock:
            return self._active_workflows.get(layer_id)

    def get_all_active_workflows(self) -> list[ManagedWorkflow]:
        """获取所有活跃工作流"""
        with self._lock:
            return [
                w
                for w in self._active_workflows.values()
                if w.state == WorkflowState.RUNNING
            ]

    def get_pending_workflows(self) -> list[ManagedWorkflow]:
        """获取待处理的工作流（按优先级排序）"""
        with self._lock:
            return [w for _, w in self._pending_workflows]

    def get_next_pending_workflow(self) -> Optional[ManagedWorkflow]:
        """获取下一个待处理的工作流（优先级最高）"""
        with self._lock:
            if self._pending_workflows:
                _, workflow = self._pending_workflows[0]
                return workflow
            return None

    def pop_next_pending_workflow(self) -> Optional[ManagedWorkflow]:
        """弹出并返回下一个待处理的工作流"""
        with self._lock:
            if self._pending_workflows:
                _, workflow = self._pending_workflows.pop(0)
                return workflow
            return None

    def get_workflow_count(self) -> dict[str, int]:
        """获取工作流统计信息"""
        with self._lock:
            counts = {
                "total": len(self._active_workflows),
                "running": sum(
                    1
                    for w in self._active_workflows.values()
                    if w.state == WorkflowState.RUNNING
                ),
                "pending": len(self._pending_workflows),
                "completed": sum(
                    1
                    for w in self._active_workflows.values()
                    if w.state == WorkflowState.COMPLETED
                ),
                "failed": sum(
                    1
                    for w in self._active_workflows.values()
                    if w.state == WorkflowState.FAILED
                ),
                "cancelled": sum(
                    1
                    for w in self._active_workflows.values()
                    if w.state == WorkflowState.CANCELLED
                ),
            }
            return counts

    def clear_completed_workflows(self, keep_recent: int = 10) -> int:
        """清理已完成的工作流记录

        Args:
            keep_recent: 保留最近 N 条记录

        Returns:
            清理的记录数
        """
        with self._lock:
            to_remove = []
            for layer_id, workflow in self._active_workflows.items():
                if workflow.state in (
                    WorkflowState.COMPLETED,
                    WorkflowState.FAILED,
                    WorkflowState.CANCELLED,
                ):
                    to_remove.append(layer_id)

            # 保留最近的记录
            if len(to_remove) > keep_recent:
                # 按创建时间排序，保留最近的
                sorted_workflows = sorted(
                    [(lid, self._active_workflows[lid]) for lid in to_remove],
                    key=lambda x: x[1].created_at,
                    reverse=True,
                )
                to_remove = [lid for lid, _ in sorted_workflows[keep_recent:]]

            for layer_id in to_remove:
                del self._active_workflows[layer_id]

            logger.info(
                f"[WorkflowLifecycleManager] Cleared {len(to_remove)} completed workflows"
            )
            return len(to_remove)

    def is_workflow_running(self, layer_id: str) -> bool:
        """检查指定图层是否有正在运行的工作流"""
        with self._lock:
            workflow = self._active_workflows.get(layer_id)
            return workflow is not None and workflow.state == WorkflowState.RUNNING

    def get_layer_workflow_state(self, layer_id: str) -> Optional[WorkflowState]:
        """获取指定图层的工作流状态"""
        with self._lock:
            workflow = self._active_workflows.get(layer_id)
            return workflow.state if workflow else None


# 全局单例
workflow_lifecycle_manager = WorkflowLifecycleManager()


# 便捷函数
def submit_weather_workflow(
    layer_id: str,
    workflow_id: str,
    priority: WorkflowPriority = WorkflowPriority.VIEWPORT,
    bbox: Optional[dict] = None,
    metadata: Optional[dict] = None,
    cancel_callback: Optional[Callable[[], Awaitable[None]]] = None,
) -> str:
    """便捷函数：提交天气工作流"""
    return workflow_lifecycle_manager.submit_workflow(
        layer_id=layer_id,
        workflow_id=workflow_id,
        priority=priority,
        bbox=bbox,
        metadata=metadata,
        cancel_callback=cancel_callback,
    )


def cancel_weather_workflow(layer_id: str) -> bool:
    """便捷函数：取消天气工作流"""
    return workflow_lifecycle_manager.cancel_workflow(layer_id)


def get_weather_workflow_state(layer_id: str) -> Optional[WorkflowState]:
    """便捷函数：获取天气工作流状态"""
    return workflow_lifecycle_manager.get_layer_workflow_state(layer_id)
