"""
Refiner - 精炼服务

精炼新闻内容，生成中文摘要，处理 refining 状态的新闻
这是后台增强步骤，不影响展示
"""

import logging

from app.database import SessionLocal
from app.models.news import News
from .error_handler import ErrorHandler
from .glm_client import glm_client

logger = logging.getLogger(__name__)


class RefinerService:
    """精炼服务 - 生成精炼内容"""

    @ErrorHandler.handle("refining")
    async def refine(self, news_id: int):
        """
        精炼新闻内容

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

            # 调用 GLM 精炼
            refined = await glm_client.refine_content(
                news.title_zh or news.title,
                news.original_content
            )

            if refined and len(refined) > 100:
                news.content = refined
                news.processing_status = 'complete'
                db.commit()
                logger.info(f"News {news_id} refined: {len(refined)} chars")
            else:
                # 精炼失败，使用原始内容的前 1000 字符
                news.content = news.original_content[:1000]
                news.processing_status = 'complete'
                db.commit()
                logger.warning(f"News {news_id} refine failed, using truncated original")

        finally:
            db.close()


# 全局单例
refiner = RefinerService()
