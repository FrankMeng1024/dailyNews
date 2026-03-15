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

            # 获取摘要作为上下文（优先使用 summary，其次 original_content）
            context = ""
            if news.summary:
                context = news.summary[:300]
            elif news.original_content:
                context = news.original_content[:300]

            # 调用 GLM 生成中文标题
            title_zh = await glm_client.generate_chinese_title(news.title, context)

            if title_zh and title_zh != news.title:
                # 清洗标题
                title_zh = self._clean_title_zh(title_zh, news.title)
                news.title_zh = title_zh[:100]  # 限制最大长度
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

    def _clean_title_zh(self, title_zh: str, original_title: str) -> str:
        """
        清洗中文标题

        Args:
            title_zh: GLM 生成的中文标题
            original_title: 原始英文标题

        Returns:
            清洗后的中文标题
        """
        if not title_zh:
            return original_title

        # 1. 去除引号、换行、首尾空白（包括中英文引号）
        title_zh = title_zh.strip().strip('"\'「」『』《》""''')

        # 2. 如果包含换行，只取第一行
        if '\n' in title_zh:
            title_zh = title_zh.split('\n')[0].strip()

        # 3. 再次清理可能残留的引号
        title_zh = title_zh.strip('"\'「」『』《》""''')

        # 4. 如果超过 50 字符，可能混入了正文，需要截断
        if len(title_zh) > 50:
            # 尝试在标点处截断
            for punct in ['。', '，', '；', '：', '——', '—', '|', '\n']:
                idx = title_zh.find(punct)
                if 0 < idx < 50:
                    title_zh = title_zh[:idx]
                    break
            else:
                # 没找到合适的标点，直接截断
                title_zh = title_zh[:40]

        # 5. 去除可能的前缀
        for prefix in ['中文标题：', '中文标题:', '标题：', '标题:', '翻译：', '翻译:']:
            if title_zh.startswith(prefix):
                title_zh = title_zh[len(prefix):].strip()

        # 6. 如果太短（<5字符），使用原标题
        if len(title_zh) < 5:
            return original_title

        return title_zh

    def _is_chinese(self, text: str) -> bool:
        """检查文本是否主要是中文"""
        if not text:
            return False
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        return chinese_chars > len(text) * 0.3


# 全局单例
translator = TranslatorService()
