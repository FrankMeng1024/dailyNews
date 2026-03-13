"""
Translator - 翻译服务

翻译新闻标题为中文，处理 translating 状态的新闻
翻译完成后 visibility_status 变为 active
"""

import logging

from app.database import SessionLocal
from app.models.news import News
from .error_handler import ErrorHandler
from .glm_client import glm_client
from .state_machine import state_machine

logger = logging.getLogger(__name__)


class TranslatorService:
    """翻译服务 - 翻译新闻标题"""

    @ErrorHandler.handle("translating")
    async def translate(self, news_id: int):
        """
        翻译新闻标题

        Args:
            news_id: 新闻 ID
        """
        db = SessionLocal()
        try:
            news = db.query(News).filter(News.id == news_id).first()
            if not news:
                logger.warning(f"News {news_id} not found")
                return

            # 更新状态为 translating
            news.processing_status = 'translating'
            db.commit()

            # 检查是否需要翻译（已有中文标题则跳过）
            if news.title_zh:
                news.processing_status = 'refining'
                news.visibility_status = 'active'
                db.commit()
                logger.info(f"News {news_id} already has Chinese title, skipping translation")
                await state_machine.enqueue(news_id)
                return

            # 检查标题是否已经是中文
            if self._is_chinese(news.title):
                news.title_zh = news.title
                news.processing_status = 'refining'
                news.visibility_status = 'active'
                db.commit()
                logger.info(f"News {news_id} title is already Chinese")
                await state_machine.enqueue(news_id)
                return

            # 调用 GLM 翻译
            context = news.original_content[:500] if news.original_content else ""
            title_zh = await glm_client.translate(news.title, context)

            if title_zh and title_zh != news.title:
                news.title_zh = title_zh[:512]
                news.processing_status = 'refining'
                news.visibility_status = 'active'  # 翻译完成即展示
                db.commit()
                logger.info(f"News {news_id} translated: {news.title[:30]}... → {title_zh[:30]}...")
                await state_machine.enqueue(news_id)
            else:
                # 翻译失败，使用原标题
                news.title_zh = news.title
                news.processing_status = 'refining'
                news.visibility_status = 'active'
                db.commit()
                logger.warning(f"News {news_id} translation failed, using original title")
                await state_machine.enqueue(news_id)

        finally:
            db.close()

    def _is_chinese(self, text: str) -> bool:
        """检查文本是否主要是中文"""
        if not text:
            return False
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        return chinese_chars > len(text) * 0.3


# 全局单例
translator = TranslatorService()
