"""
Verifier - 验证服务

验证新闻内容的 AI 相关性，处理 verifying 状态的新闻
"""

import logging

from app.database import SessionLocal
from app.models.news import News
from .error_handler import ErrorHandler
from .glm_client import glm_client
from .state_machine import state_machine

logger = logging.getLogger(__name__)

# AI 关键词（快速预筛选）
AI_KEYWORDS = [
    'ai', 'artificial intelligence', 'machine learning', 'deep learning',
    'neural', 'gpt', 'llm', 'chatgpt', 'openai', 'anthropic', 'claude',
    'gemini', 'mistral', 'llama', 'transformer', 'diffusion'
]


class VerifierService:
    """验证服务 - 验证新闻的 AI 相关性"""

    @ErrorHandler.handle("verifying")
    async def verify(self, news_id: int):
        """
        验证新闻内容

        Args:
            news_id: 新闻 ID
        """
        db = SessionLocal()
        try:
            news = db.query(News).filter(News.id == news_id).first()
            if not news:
                logger.warning(f"News {news_id} not found")
                return

            # 更新状态为 verifying
            news.processing_status = 'verifying'
            db.commit()

            # 快速关键词预筛选
            text = f"{news.title} {news.original_content or ''}"
            if self._quick_check(text):
                # 关键词匹配，直接通过
                news.verification_score = 0.7
                news.verification_result = {"method": "keyword", "passed": True}
                news.processing_status = 'translating'
                db.commit()
                logger.info(f"News {news_id} verified by keyword match")
                await state_machine.enqueue(news_id)
                return

            # 使用 GLM 深度验证
            result = await glm_client.verify_ai_relevance(
                news.title,
                news.original_content[:500] if news.original_content else ""
            )

            news.verification_score = result.get("relevance_score", 0.5)
            news.verification_result = result

            if result.get("is_ai_related", True):
                # 验证通过
                news.processing_status = 'translating'
                db.commit()
                logger.info(f"News {news_id} verified by GLM: score {news.verification_score:.2f}")
                await state_machine.enqueue(news_id)
            else:
                # 验证不通过，标记为 skip
                news.visibility_status = 'skip'
                news.processing_status = 'complete'
                db.commit()
                logger.info(f"News {news_id} skipped: not AI related (score {news.verification_score:.2f})")

        finally:
            db.close()

    def _quick_check(self, text: str) -> bool:
        """快速关键词检查"""
        if not text:
            return False
        text_lower = text.lower()
        return any(kw in text_lower for kw in AI_KEYWORDS)


# 全局单例
verifier = VerifierService()
