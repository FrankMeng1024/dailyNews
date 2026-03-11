"""
异步任务工具

提供安全的异步任务创建和管理，确保异常被正确捕获和记录
"""

import asyncio
import logging
from typing import Coroutine, Any, Optional, Callable
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def create_safe_task(
    coro: Coroutine,
    task_name: str = "background_task",
    on_error: Optional[Callable[[Exception], None]] = None
) -> asyncio.Task:
    """创建带异常处理的后台任务

    Args:
        coro: 要执行的协程
        task_name: 任务名称（用于日志）
        on_error: 错误回调函数

    Returns:
        asyncio.Task 对象

    使用方式:
        # 替代 asyncio.create_task(some_coro())
        create_safe_task(some_coro(), task_name="my_task")
    """
    async def wrapped():
        try:
            return await coro
        except asyncio.CancelledError:
            logger.info(f"Background task '{task_name}' was cancelled")
            raise
        except Exception as e:
            logger.error(
                f"Background task '{task_name}' failed: {e}",
                exc_info=True
            )
            # 记录到数据库
            await _record_task_failure(task_name, e)
            # 调用错误回调
            if on_error:
                try:
                    on_error(e)
                except Exception as callback_error:
                    logger.error(f"Error callback failed: {callback_error}")

    task = asyncio.create_task(wrapped())
    task.set_name(task_name)
    return task


async def _record_task_failure(task_name: str, error: Exception) -> None:
    """记录任务失败到数据库

    Args:
        task_name: 任务名称
        error: 异常对象
    """
    try:
        from app.database_utils import async_safe_db_session
        from app.models.retry_history import RetryHistory

        async with async_safe_db_session() as db:
            error_msg = f"[{task_name}] {type(error).__name__}: {str(error)}"
            record = RetryHistory(
                trigger_type='background_task_failure',
                error_message=error_msg[:500],
                created_at=datetime.now(timezone.utc)
            )
            db.add(record)
            db.commit()
    except Exception as db_error:
        # 记录失败不应该影响主流程
        logger.error(f"Failed to record task failure to database: {db_error}")


async def run_with_timeout(
    coro: Coroutine,
    timeout_seconds: float,
    task_name: str = "timed_task"
) -> Any:
    """运行协程并设置超时

    Args:
        coro: 要执行的协程
        timeout_seconds: 超时秒数
        task_name: 任务名称（用于日志）

    Returns:
        协程的返回值

    Raises:
        asyncio.TimeoutError: 超时时抛出
    """
    try:
        return await asyncio.wait_for(coro, timeout=timeout_seconds)
    except asyncio.TimeoutError:
        logger.warning(f"Task '{task_name}' timed out after {timeout_seconds}s")
        raise


async def gather_with_exceptions(
    *coros: Coroutine,
    return_exceptions: bool = True
) -> list:
    """并发执行多个协程，收集结果和异常

    Args:
        *coros: 要执行的协程
        return_exceptions: 是否将异常作为结果返回

    Returns:
        结果列表（可能包含异常对象）
    """
    results = await asyncio.gather(*coros, return_exceptions=return_exceptions)

    # 记录异常
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.warning(f"Task {i} failed with: {result}")

    return results


class TaskGroup:
    """任务组管理器

    用于管理一组相关的后台任务
    """

    def __init__(self, name: str = "task_group"):
        self.name = name
        self.tasks: list[asyncio.Task] = []

    def add_task(self, coro: Coroutine, task_name: Optional[str] = None) -> asyncio.Task:
        """添加任务到组

        Args:
            coro: 协程
            task_name: 任务名称

        Returns:
            创建的任务
        """
        full_name = f"{self.name}.{task_name}" if task_name else self.name
        task = create_safe_task(coro, task_name=full_name)
        self.tasks.append(task)
        return task

    async def wait_all(self, timeout: Optional[float] = None) -> list:
        """等待所有任务完成

        Args:
            timeout: 超时秒数

        Returns:
            所有任务的结果
        """
        if not self.tasks:
            return []

        if timeout:
            done, pending = await asyncio.wait(
                self.tasks,
                timeout=timeout,
                return_when=asyncio.ALL_COMPLETED
            )
            # 取消未完成的任务
            for task in pending:
                task.cancel()
            return [task.result() if task.done() and not task.cancelled() else None
                    for task in self.tasks]
        else:
            return await asyncio.gather(*self.tasks, return_exceptions=True)

    def cancel_all(self) -> None:
        """取消所有任务"""
        for task in self.tasks:
            if not task.done():
                task.cancel()
        logger.info(f"Cancelled all tasks in group '{self.name}'")

    @property
    def pending_count(self) -> int:
        """获取未完成任务数"""
        return sum(1 for task in self.tasks if not task.done())

    @property
    def completed_count(self) -> int:
        """获取已完成任务数"""
        return sum(1 for task in self.tasks if task.done())
