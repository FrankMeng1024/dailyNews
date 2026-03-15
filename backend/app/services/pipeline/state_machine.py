"""
State Machine - 状态机服务

管理新闻处理流水线的任务调度：
- 使用 asyncio.PriorityQueue 作为优先级队列
- 根据 processing_status 分配下一步任务
- 优先处理影响展示的任务（created/fetching/verifying/translating）
- refining 任务优先级最低（不影响展示）
- 支持重启后从数据库恢复未完成任务
"""

import asyncio
import logging
from typing import Optional, Callable, Dict, Any

from app.database import SessionLocal
from app.models.news import News

logger = logging.getLogger(__name__)

# 状态优先级定义（数字越小优先级越高）
STATUS_PRIORITY = {
    'created': 1,      # 新文章，需要尽快处理
    'fetching': 1,     # 抓取中，需要完成
    'verifying': 2,    # 验证中
    'translating': 3,  # 翻译中，完成后可展示
    'refining': 4,     # 精炼，不影响展示
}


class StateMachineService:
    """状态机服务 - 管理新闻处理流水线"""

    def __init__(self):
        self.queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self.running: bool = False
        self._worker_task: Optional[asyncio.Task] = None
        self._step_handlers: Dict[str, Callable] = {}
        self._counter: int = 0  # 用于保证相同优先级时的 FIFO 顺序

        # SSE 事件队列（用于实时推送）
        self.event_queues: Dict[str, asyncio.Queue] = {}

    def register_handler(self, status: str, handler: Callable):
        """
        注册状态处理器

        Args:
            status: processing_status 值
            handler: 处理函数，签名为 async def handler(news_id: int)
        """
        self._step_handlers[status] = handler
        logger.info(f"Registered handler for status: {status}")

    async def start(self):
        """启动状态机"""
        if self.running:
            logger.warning("State machine already running")
            return

        self.running = True
        logger.info("State machine starting...")

        # 从数据库恢复未完成的任务
        await self._recover_pending_tasks()

        # 启动 worker
        self._worker_task = asyncio.create_task(self._worker())
        logger.info("State machine started")

    async def stop(self):
        """停止状态机"""
        self.running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        logger.info("State machine stopped")

    async def enqueue(self, news_id: int, status: str = None):
        """
        将新闻放入处理队列（带优先级）

        Args:
            news_id: 新闻 ID
            status: 可选的状态，用于确定优先级。如果不提供，从数据库获取
        """
        if status is None:
            # 从数据库获取状态
            db = SessionLocal()
            try:
                news = db.query(News).filter(News.id == news_id).first()
                status = news.processing_status if news else 'refining'
            finally:
                db.close()

        priority = STATUS_PRIORITY.get(status, 4)
        self._counter += 1
        # 使用 (priority, counter, news_id) 确保相同优先级时按 FIFO 顺序
        await self.queue.put((priority, self._counter, news_id))
        logger.debug(f"Enqueued news {news_id} with priority {priority}, queue size: {self.queue.qsize()}")

    async def enqueue_batch(self, news_ids: list):
        """
        批量放入队列

        Args:
            news_ids: 新闻 ID 列表
        """
        for news_id in news_ids:
            await self.enqueue(news_id)
        logger.info(f"Enqueued {len(news_ids)} news items")

    async def _recover_pending_tasks(self):
        """从数据库恢复未完成的任务"""
        db = SessionLocal()
        try:
            # 查找所有未完成的新闻（processing_status 不是 complete 的）
            # 注意：翻译完成后 visibility_status 变为 active，但 refining 还未完成
            pending = db.query(News).filter(
                News.processing_status != 'complete',
                News.visibility_status != 'failed'  # 排除失败的，需要手动重试
            ).all()

            if pending:
                logger.info(f"Recovering {len(pending)} pending tasks")
                for news in pending:
                    await self.enqueue(news.id, news.processing_status)
            else:
                logger.info("No pending tasks to recover")

        except Exception as e:
            logger.error(f"Failed to recover pending tasks: {e}")
        finally:
            db.close()

    async def _worker(self):
        """消费队列，分配任务"""
        logger.info("Worker started")
        while self.running:
            try:
                # 等待队列中的任务，超时后继续循环检查 running 状态
                try:
                    item = await asyncio.wait_for(self.queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue

                # 从优先级队列中解包 (priority, counter, news_id)
                if isinstance(item, tuple):
                    _, _, news_id = item
                else:
                    news_id = item  # 兼容旧格式

                # 处理任务
                await self._process(news_id)
                self.queue.task_done()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Worker error: {e}")
                await asyncio.sleep(1)  # 避免错误循环

        logger.info("Worker stopped")

    async def _process(self, news_id: int):
        """
        根据状态分配下一个任务

        Args:
            news_id: 新闻 ID
        """
        db = SessionLocal()
        try:
            news = db.query(News).filter(News.id == news_id).first()
            if not news:
                logger.warning(f"News {news_id} not found")
                return

            # 如果是 failed 状态，清除错误继续处理
            if news.visibility_status == 'failed':
                news.visibility_status = 'inactive'
                news.last_error = None
                db.commit()
                logger.info(f"News {news_id} retry: cleared failed status")

            # 如果已完成，跳过
            if news.processing_status == 'complete':
                logger.debug(f"News {news_id} already complete")
                return

            # 获取下一步处理器
            handler = self._step_handlers.get(news.processing_status)
            if handler:
                logger.info(f"Processing news {news_id}, status: {news.processing_status}")
                await handler(news_id)
            else:
                logger.warning(f"No handler for status: {news.processing_status}")

        except Exception as e:
            logger.error(f"Process error for news {news_id}: {e}")
        finally:
            db.close()

    # ========== SSE 事件支持 ==========

    def create_event_queue(self, task_id: str) -> asyncio.Queue:
        """创建 SSE 事件队列"""
        queue = asyncio.Queue()
        self.event_queues[task_id] = queue
        return queue

    def remove_event_queue(self, task_id: str):
        """移除 SSE 事件队列"""
        if task_id in self.event_queues:
            del self.event_queues[task_id]

    async def emit_event(self, task_id: str, event_type: str, **data):
        """
        发送 SSE 事件

        Args:
            task_id: 任务 ID
            event_type: 事件类型
            **data: 事件数据
        """
        queue = self.event_queues.get(task_id)
        if queue:
            await queue.put({"type": event_type, **data})

    def get_queue_size(self) -> int:
        """获取队列大小"""
        return self.queue.qsize()

    def is_running(self) -> bool:
        """检查是否运行中"""
        return self.running


# 全局单例
state_machine = StateMachineService()
