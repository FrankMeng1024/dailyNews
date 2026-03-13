"""
Pipeline Services - 新闻处理流水线

状态机设计：
- processing_status: created → fetching → verifying → translating → refining → complete
- visibility_status: inactive → active / skip / failed

核心原则：
1. 状态即进度：当前 processing_status 就是正在执行的步骤
2. 失败不丢：失败时 visibility_status=failed，processing_status 保持不变
3. 翻译即展示：翻译完成后 visibility_status=active
4. 并发控制：GLM 调用通过 Semaphore 限制并发数
5. 队列驱动：所有任务通过 asyncio.Queue 调度
"""

from .state_machine import state_machine
from .glm_client import glm_client
from .error_handler import ErrorHandler
from .basic_fetcher import basic_fetcher
from .content_fetcher import content_fetcher
from .verifier import verifier
from .translator import translator
from .refiner import refiner


def register_handlers():
    """注册所有状态处理器到状态机"""
    state_machine.register_handler('created', content_fetcher.fetch)
    state_machine.register_handler('fetching', content_fetcher.fetch)
    state_machine.register_handler('verifying', verifier.verify)
    state_machine.register_handler('translating', translator.translate)
    state_machine.register_handler('refining', refiner.refine)


__all__ = [
    'state_machine',
    'glm_client',
    'ErrorHandler',
    'basic_fetcher',
    'content_fetcher',
    'verifier',
    'translator',
    'refiner',
    'register_handlers',
]
