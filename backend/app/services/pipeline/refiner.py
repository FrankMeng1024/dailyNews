"""
Refiner - 精炼服务

精炼新闻内容，生成中文摘要，处理 refining 状态的新闻
使用三阶段精炼：提取关键信息 → 精炼改写 → 验证校对
"""

import logging

from app.database import SessionLocal
from app.models.news import News
from .error_handler import ErrorHandler
from .glm_client import glm_client

logger = logging.getLogger(__name__)


class RefinerService:
    """精炼服务 - 使用三阶段精炼生成高质量内容"""

    @ErrorHandler.handle("refining")
    async def refine(self, news_id: int):
        """
        精炼新闻内容（三阶段流程）

        Args:
            news_id: 新闻 ID
        """
        db = SessionLocal()
        try:
            news = db.query(News).filter(News.id == news_id).first()
            if not news:
                logger.warning(f"News {news_id} not found")
                return

            # 更新状态为 refining
            news.processing_status = 'refining'
            db.commit()

            # 检查是否已有精炼内容
            if news.content and len(news.content) > 100:
                news.processing_status = 'complete'
                db.commit()
                logger.info(f"News {news_id} already has refined content")
                return

            # 检查是否有原始内容可供精炼
            if not news.original_content or len(news.original_content) < 100:
                # 没有足够内容，使用 summary 或跳过
                if news.summary and len(news.summary) > 50:
                    news.content = news.summary
                news.processing_status = 'complete'
                db.commit()
                logger.info(f"News {news_id} no content to refine, using summary")
                return

            # 使用三阶段精炼
            refined = await glm_client.refine_content_three_stage(
                news.title_zh or news.title,
                news.original_content,
                news.source_type or "news"
            )

            if refined and len(refined) > 100:
                news.content = refined
                news.processing_status = 'complete'
                db.commit()
                logger.info(f"News {news_id} refined (3-stage): {len(refined)} chars")
            else:
                # 三阶段失败，降级到单次精炼
                logger.warning(f"News {news_id} 3-stage failed, fallback to single-stage")
                refined = await glm_client.refine_content(
                    news.title_zh or news.title,
                    news.original_content
                )
                if refined and len(refined) > 100:
                    news.content = refined
                else:
                    # 精炼失败，使用原始内容的前 1000 字符
                    news.content = news.original_content[:1000]
                news.processing_status = 'complete'
                db.commit()

        finally:
            db.close()


# 全局单例
refiner = RefinerService()
