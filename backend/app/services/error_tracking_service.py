"""
统一错误追踪服务

提供错误记录、格式化和追踪功能
"""

from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.orm import Session
import logging
import traceback

from app.models.news import News
from app.services.config_service import DEFAULT_CONFIG

logger = logging.getLogger(__name__)


class ErrorTracker:
    """统一错误追踪服务"""

    @staticmethod
    def record_glm_error(
        db: Session,
        news: News,
        error: Exception,
        context: str = ""
    ) -> None:
        """记录 GLM 错误

        Args:
            db: 数据库会话
            news: 新闻对象
            error: 异常对象
            context: 额外上下文信息
        """
        max_error_len = DEFAULT_CONFIG["max_error_message_length"]
        max_retries = DEFAULT_CONFIG["max_retries"]

        error_msg = ErrorTracker._format_error(error, context)

        news.glm_last_error = error_msg[:max_error_len]
        news.glm_retry_count = (news.glm_retry_count or 0) + 1

        if news.glm_retry_count >= max_retries:
            news.content_status = "failed"
        else:
            news.content_status = "pending"

        logger.error(f"GLM error for news {news.id}: {error_msg}")
        db.commit()

    @staticmethod
    def record_scrape_error(
        db: Session,
        news: News,
        error: Exception,
        url: str = ""
    ) -> None:
        """记录爬虫错误

        Args:
            db: 数据库会话
            news: 新闻对象
            error: 异常对象
            url: 爬取的 URL
        """
        max_error_len = DEFAULT_CONFIG["max_error_message_length"]

        error_msg = ErrorTracker._format_error(error, f"URL: {url}")

        news.scraping_last_error = error_msg[:max_error_len]
        news.scraping_retry_count = (news.scraping_retry_count or 0) + 1

        logger.error(f"Scrape error for news {news.id}: {error_msg}")
        db.commit()

    @staticmethod
    def record_title_error(
        db: Session,
        news: News,
        error: Exception,
        context: str = ""
    ) -> None:
        """记录标题翻译错误

        Args:
            db: 数据库会话
            news: 新闻对象
            error: 异常对象
            context: 额外上下文信息
        """
        max_error_len = DEFAULT_CONFIG["max_error_message_length"]
        max_retries = DEFAULT_CONFIG["max_retries"]

        error_msg = ErrorTracker._format_error(error, context)

        news.title_last_error = error_msg[:max_error_len]
        news.title_retry_count = (news.title_retry_count or 0) + 1

        if news.title_retry_count >= max_retries:
            news.title_status = "failed"
        else:
            news.title_status = "pending"

        logger.error(f"Title translation error for news {news.id}: {error_msg}")
        db.commit()

    @staticmethod
    def _format_error(error: Exception, context: str = "") -> str:
        """格式化错误信息

        Args:
            error: 异常对象
            context: 额外上下文信息

        Returns:
            格式化后的错误字符串
        """
        error_type = type(error).__name__
        error_msg = str(error)

        # 包含堆栈的前几行
        tb = traceback.format_exc()
        tb_lines = tb.split('\n')
        # 取最后5行有意义的堆栈信息
        tb_short = '\n'.join([line for line in tb_lines[-6:] if line.strip()])

        parts = [f"[{error_type}] {error_msg}"]
        if context:
            parts.append(f"Context: {context}")
        if tb_short and "NoneType" not in tb_short:
            parts.append(tb_short)

        return '\n'.join(parts)

    @staticmethod
    def is_retryable_error(error: Exception) -> bool:
        """检查错误是否可重试

        Args:
            error: 异常对象

        Returns:
            True 如果错误是可重试的（网络/超时问题）
        """
        error_str = str(error).lower()
        retryable_keywords = [
            'timeout', 'connection', 'connect', 'network',
            'reset', 'refused', 'unavailable', 'temporary',
            '429', 'rate limit', 'too many requests'
        ]
        return any(kw in error_str for kw in retryable_keywords)

    @staticmethod
    def get_error_summary(db: Session) -> dict:
        """获取错误统计摘要

        Args:
            db: 数据库会话

        Returns:
            错误统计字典
        """
        from sqlalchemy import func

        # GLM 错误统计
        glm_pending = db.query(func.count(News.id)).filter(
            News.content_status == "pending"
        ).scalar() or 0

        glm_failed = db.query(func.count(News.id)).filter(
            News.content_status == "failed"
        ).scalar() or 0

        # 爬虫错误统计
        scrape_failed = db.query(func.count(News.id)).filter(
            News.scraping_retry_count >= DEFAULT_CONFIG["max_retries"]
        ).scalar() or 0

        # 标题翻译错误统计
        title_pending = db.query(func.count(News.id)).filter(
            News.title_status == "pending"
        ).scalar() or 0

        title_failed = db.query(func.count(News.id)).filter(
            News.title_status == "failed"
        ).scalar() or 0

        return {
            "glm": {
                "pending": glm_pending,
                "failed": glm_failed
            },
            "scraping": {
                "failed": scrape_failed
            },
            "title_translation": {
                "pending": title_pending,
                "failed": title_failed
            },
            "total_issues": glm_pending + glm_failed + scrape_failed + title_pending + title_failed
        }


# 单例实例
error_tracker = ErrorTracker()
