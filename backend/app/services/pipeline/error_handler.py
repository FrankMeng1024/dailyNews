"""
Error Handler - 错误处理装饰器

统一处理 pipeline 中各步骤的错误，记录到 News 模型
"""

import logging
from functools import wraps
from typing import Callable, Any

from app.database import SessionLocal
from app.models.news import News

logger = logging.getLogger(__name__)


class ErrorHandler:
    """Pipeline 错误处理装饰器"""

    @staticmethod
    def handle(step_name: str):
        """
        装饰器：捕获异常并记录到 News 模型

        Args:
            step_name: 步骤名称 (fetching/verifying/translating/refining)

        Usage:
            @ErrorHandler.handle("fetching")
            async def fetch(self, news_id: int):
                ...
        """
        def decorator(func: Callable) -> Callable:
            @wraps(func)
            async def wrapper(self, news_id: int, *args, **kwargs) -> Any:
                db = SessionLocal()
                try:
                    return await func(self, news_id, *args, **kwargs)
                except Exception as e:
                    # 记录错误到数据库
                    try:
                        news = db.query(News).filter(News.id == news_id).first()
                        if news:
                            news.visibility_status = 'failed'
                            news.last_error = str(e)[:500]
                            news.error_step = step_name
                            news.retry_count = (news.retry_count or 0) + 1
                            db.commit()
                            logger.error(f"[{step_name}] News {news_id} failed: {e}")
                        else:
                            logger.error(f"[{step_name}] News {news_id} not found, error: {e}")
                    except Exception as db_error:
                        logger.error(f"[{step_name}] Failed to record error for news {news_id}: {db_error}")
                        db.rollback()
                    # 不 raise，让队列继续处理下一个
                    return None
                finally:
                    db.close()
            return wrapper
        return decorator
