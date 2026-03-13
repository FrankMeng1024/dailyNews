"""
Content Fetcher - 内容抓取服务

抓取文章全文内容，处理 created 状态的新闻
"""

import asyncio
import httpx
import logging
import re
from typing import Optional
from bs4 import BeautifulSoup

from app.database import SessionLocal
from app.models.news import News
from .error_handler import ErrorHandler
from .state_machine import state_machine

logger = logging.getLogger(__name__)

# 最小内容长度
MIN_CONTENT_LENGTH = 200

# 质量评分阈值（低于此值标记为 skip）
MIN_QUALITY_THRESHOLD = 0.3


class ContentFetcherService:
    """内容抓取服务"""

    def __init__(self):
        self.timeout = 30.0

    @ErrorHandler.handle("fetching")
    async def fetch(self, news_id: int):
        """
        抓取文章全文

        Args:
            news_id: 新闻 ID
        """
        db = SessionLocal()
        try:
            news = db.query(News).filter(News.id == news_id).first()
            if not news:
                logger.warning(f"News {news_id} not found")
                return

            # 更新状态为 fetching
            news.processing_status = 'fetching'
            db.commit()

            # 抓取内容
            content = await self._scrape_content(news.source_url)

            if content and len(content) >= MIN_CONTENT_LENGTH:
                # 抓取成功
                news.original_content = content

                # 计算质量评分
                score = self._calculate_quality_score(news, content)
                news.quality_score = score

                # 判断是否 skip
                if score < MIN_QUALITY_THRESHOLD:
                    news.visibility_status = 'skip'
                    news.processing_status = 'complete'
                    db.commit()
                    logger.info(f"News {news_id} skipped: quality score {score:.2f} < {MIN_QUALITY_THRESHOLD}")
                    return

                # 成功，进入下一步
                news.processing_status = 'verifying'
                db.commit()
                logger.info(f"News {news_id} fetched: {len(content)} chars, score {score:.2f}")

                # 放入队列继续处理
                await state_machine.enqueue(news_id)

            else:
                # 抓取失败，尝试使用 summary 作为备用
                fallback = news.summary or ""
                if len(fallback) >= 100:
                    news.original_content = fallback
                    news.processing_status = 'verifying'
                    db.commit()
                    logger.info(f"News {news_id} using summary as fallback: {len(fallback)} chars")
                    await state_machine.enqueue(news_id)
                else:
                    # 真正失败
                    raise Exception(f"Content too short: {len(content or '')} chars")

        finally:
            db.close()

    async def _scrape_content(self, url: str) -> Optional[str]:
        """抓取网页内容"""
        if not url:
            return None

        # HN 讨论页不抓取
        if url.startswith("https://news.ycombinator.com"):
            return None

        # GitHub 特殊处理
        if 'github.com' in url:
            content = await self._scrape_github(url)
            if content:
                return content

        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                    "Accept": "text/html,application/xhtml+xml",
                }
                resp = await client.get(url, headers=headers)

                if resp.status_code != 200:
                    return None

                soup = BeautifulSoup(resp.text, 'html.parser')

                # 移除无用元素
                for tag in soup.find_all(['script', 'style', 'nav', 'header', 'footer',
                                          'aside', 'iframe', 'noscript', 'form']):
                    tag.decompose()

                # 尝试多种选择器
                content = None
                selectors = [
                    'article', '[role="main"]', '.article-content', '.post-content',
                    '.entry-content', 'main', '#content', '.prose', '.markdown-body'
                ]

                for selector in selectors:
                    element = soup.select_one(selector)
                    if element:
                        content = self._extract_text(element)
                        if content and len(content) >= MIN_CONTENT_LENGTH:
                            break
                        content = None

                # 备用：收集所有段落
                if not content:
                    paragraphs = soup.find_all('p')
                    texts = [p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 30]
                    if texts:
                        content = '\n\n'.join(texts[:30])

                # 验证内容质量
                if content and self._is_valid_content(content):
                    return content[:30000]

                return None

        except Exception as e:
            logger.warning(f"Scrape error for {url[:50]}: {e}")
            return None

    async def _scrape_github(self, url: str) -> Optional[str]:
        """GitHub 页面特殊处理"""
        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                # blob 页面转 raw
                if '/blob/' in url:
                    raw_url = url.replace('github.com', 'raw.githubusercontent.com').replace('/blob/', '/')
                    resp = await client.get(raw_url)
                    if resp.status_code == 200:
                        return resp.text[:30000]

                # 仓库主页获取 README
                parts = url.rstrip('/').split('/')
                if len(parts) >= 5 and parts[2] == 'github.com':
                    user, repo = parts[3], parts[4]
                    for branch in ['main', 'master']:
                        readme_url = f"https://raw.githubusercontent.com/{user}/{repo}/{branch}/README.md"
                        resp = await client.get(readme_url)
                        if resp.status_code == 200 and len(resp.text) > 100:
                            return resp.text[:30000]

                return None

        except Exception as e:
            logger.warning(f"GitHub scrape error: {e}")
            return None

    def _extract_text(self, element) -> Optional[str]:
        """从元素提取文本"""
        texts = []
        for p in element.find_all('p'):
            text = p.get_text(strip=True)
            if len(text) > 40:
                texts.append(text)

        if texts:
            return '\n\n'.join(texts)
        return None

    def _is_valid_content(self, content: str) -> bool:
        """验证内容质量"""
        if not content or len(content) < 100:
            return False

        content_lower = content.lower()

        # 检查错误页面特征
        error_patterns = ['404', 'not found', 'page not found', 'error', 'forbidden',
                         'access denied', 'login required', 'enable javascript']
        first_500 = content_lower[:500]
        if sum(1 for p in error_patterns if p in first_500) >= 2:
            return False

        # 检查省略号过多
        if content.count('...') + content.count('…') > 10:
            return False

        # 检查内容多样性
        lines = [l.strip() for l in content.split('\n') if l.strip()]
        if len(lines) < 3:
            return False

        return True

    def _calculate_quality_score(self, news: News, content: str) -> float:
        """计算质量评分"""
        score = 0.5  # 基础分

        # 内容长度加分
        if len(content) > 500:
            score += 0.1
        if len(content) > 1000:
            score += 0.1
        if len(content) > 2000:
            score += 0.1

        # 来源加分
        trusted_sources = ['openai', 'anthropic', 'google', 'microsoft', 'meta', 'deepmind']
        source_lower = (news.source_name or '').lower()
        if any(s in source_lower for s in trusted_sources):
            score += 0.2

        return min(1.0, score)


# 全局单例
content_fetcher = ContentFetcherService()
