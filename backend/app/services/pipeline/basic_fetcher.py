"""
Basic Fetcher - 基础抓取服务

从 RSS/API 获取新闻基本信息，创建 News 记录
"""

import asyncio
import hashlib
import httpx
import feedparser
import logging
from datetime import datetime, timezone
from time import mktime
from typing import List, Dict, Any, Optional
from bs4 import BeautifulSoup

from app.database import SessionLocal
from app.models.news import News
from app.config import settings

logger = logging.getLogger(__name__)

# AI 关键词列表
AI_KEYWORDS = [
    'ai', 'artificial intelligence', 'machine learning', 'deep learning',
    'neural network', 'gpt', 'llm', 'large language model', 'chatgpt',
    'openai', 'anthropic', 'claude', 'gemini', 'mistral', 'llama',
    'transformer', 'diffusion', 'stable diffusion', 'midjourney',
    'deepseek', 'copilot', 'agent', 'rag', 'embedding', 'vector'
]

# 尝试导入配置的 AI 源
try:
    from app.config_sources.ai_sources import VERIFIED_AI_SOURCES
except ImportError:
    VERIFIED_AI_SOURCES = {}


class BasicFetcherService:
    """基础抓取服务 - 从 RSS/API 获取新闻"""

    def __init__(self):
        self.api_key = settings.NEWS_API_KEY
        self.news_api_url = settings.NEWS_API_URL

    def generate_external_id(self, url: str, title: str = "") -> str:
        """生成去重用的 external_id"""
        content = f"{url}{title}"
        return hashlib.md5(content.encode()).hexdigest()

    def is_ai_related(self, text: str) -> bool:
        """检查内容是否与 AI 相关"""
        if not text:
            return False
        text_lower = text.lower()
        return any(kw in text_lower for kw in AI_KEYWORDS)

    async def fetch_all_sources(self, limit_per_source: int = 10) -> List[Dict[str, Any]]:
        """
        从所有源抓取新闻

        Args:
            limit_per_source: 每个源的最大数量

        Returns:
            文章列表
        """
        all_articles = []

        # 并行抓取所有源
        tasks = [
            self.fetch_rss_feeds(limit_per_source),
            self.fetch_hackernews(limit_per_source),
            self.fetch_reddit(limit_per_source),
        ]

        # 如果配置了 NewsAPI
        if self.api_key and self.api_key != "your_newsapi_key_here":
            tasks.append(self.fetch_newsapi(limit_per_source))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Fetch source {i} error: {result}")
            elif result:
                all_articles.extend(result)

        logger.info(f"Total articles fetched: {len(all_articles)}")
        return all_articles

    async def fetch_rss_feeds(self, limit_per_source: int = 10) -> List[Dict[str, Any]]:
        """从 RSS 源抓取

        Args:
            limit_per_source: RSS 总数限制（所有 RSS 源合计）
        """
        if not VERIFIED_AI_SOURCES:
            logger.info("No verified AI sources configured")
            return []

        articles = []
        rss_sources = [
            (source_id, info)
            for source_id, info in VERIFIED_AI_SOURCES.items()
            if "rss_url" in info
        ]

        if not rss_sources:
            return []

        # 计算每个 RSS 源的限制（平均分配，至少 1 条）
        per_feed_limit = max(1, limit_per_source // len(rss_sources))

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            tasks = [client.get(info["rss_url"]) for _, info in rss_sources]
            responses = await asyncio.gather(*tasks, return_exceptions=True)

            for (source_id, info), response in zip(rss_sources, responses):
                # 检查是否已达到总数限制
                if len(articles) >= limit_per_source:
                    break

                if isinstance(response, Exception):
                    logger.warning(f"RSS fetch error for {info['name']}: {response}")
                    continue

                if response.status_code != 200:
                    continue

                try:
                    feed = feedparser.parse(response.text)
                    if not feed.entries:
                        continue

                    count = 0
                    for entry in feed.entries:
                        # 检查单源限制和总数限制
                        if count >= per_feed_limit or len(articles) >= limit_per_source:
                            break

                        # 解析发布时间
                        published_at = self._parse_feed_time(entry)

                        # 对于 discussion 类型，检查 AI 相关性（过滤垃圾内容）
                        if info.get("type") == "discussion":
                            title = entry.title if hasattr(entry, 'title') else ""
                            desc = entry.summary if hasattr(entry, 'summary') else ""
                            if not self.is_ai_related(f"{title} {desc}"):
                                continue

                        # 解析描述
                        description = ""
                        if hasattr(entry, 'summary'):
                            description = entry.summary
                        elif hasattr(entry, 'description'):
                            description = entry.description

                        # 清理 HTML 标签
                        description_text = ""
                        if description:
                            soup = BeautifulSoup(description, 'html.parser')
                            description_text = soup.get_text(strip=True)

                        # 对于 rss_content 类型，保存完整内容
                        fetch_method = info.get("fetch_method", "generic")
                        if fetch_method == "rss_content" and description_text:
                            # 保存完整内容，不截断
                            summary = description_text[:30000]
                        else:
                            summary = description_text[:500] if description_text else None

                        articles.append({
                            "title": entry.title if hasattr(entry, 'title') else "Untitled",
                            "url": entry.link if hasattr(entry, 'link') else "",
                            "source_name": info["name"],
                            "source_type": info.get("type", "news"),
                            "published_at": published_at,
                            "summary": summary,
                            "author": entry.author if hasattr(entry, 'author') else None,
                            "is_verified": info.get("verified", False),
                            "fetch_method": fetch_method,  # 传递抓取方法
                        })
                        count += 1

                    logger.info(f"RSS: {info['name']} - {count} articles")

                except Exception as e:
                    logger.error(f"RSS parse error for {info['name']}: {e}")

        logger.info(f"RSS total: {len(articles)} articles (limit: {limit_per_source})")
        return articles

    async def fetch_hackernews(self, limit: int = 15) -> List[Dict[str, Any]]:
        """从 Hacker News 抓取 AI 相关内容"""
        articles = []

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                resp = await client.get("https://hacker-news.firebaseio.com/v0/topstories.json")
                story_ids = resp.json()[:100]

                # 批量获取故事详情
                batch_size = 20
                for i in range(0, len(story_ids), batch_size):
                    if len(articles) >= limit:
                        break

                    batch_ids = story_ids[i:i + batch_size]
                    tasks = [
                        client.get(f"https://hacker-news.firebaseio.com/v0/item/{sid}.json")
                        for sid in batch_ids
                    ]
                    responses = await asyncio.gather(*tasks, return_exceptions=True)

                    for story_id, resp in zip(batch_ids, responses):
                        if isinstance(resp, Exception):
                            continue

                        story = resp.json()
                        if not story or story.get("type") != "story":
                            continue

                        title = story.get("title", "")
                        if not self.is_ai_related(title):
                            continue

                        articles.append({
                            "title": title,
                            "url": story.get("url", f"https://news.ycombinator.com/item?id={story_id}"),
                            "source_name": "Hacker News",
                            "source_type": "discussion",
                            "published_at": datetime.fromtimestamp(story.get("time", 0), tz=timezone.utc),
                            "summary": f"Score: {story.get('score', 0)} | Comments: {story.get('descendants', 0)}",
                            "author": story.get("by"),
                            "is_verified": False,
                        })

                        if len(articles) >= limit:
                            break

                logger.info(f"HackerNews: {len(articles)} AI articles")

            except Exception as e:
                logger.error(f"HackerNews error: {e}")

        return articles

    async def fetch_reddit(self, limit: int = 15) -> List[Dict[str, Any]]:
        """从 Reddit AI 相关 subreddit 抓取"""
        subreddits = ["MachineLearning", "artificial", "LocalLLaMA"]
        articles = []

        async with httpx.AsyncClient(timeout=30.0) as client:
            tasks = [
                client.get(
                    f"https://www.reddit.com/r/{sub}/hot.json?limit=10",
                    headers={"User-Agent": "AINewsBot/1.0"}
                )
                for sub in subreddits
            ]
            responses = await asyncio.gather(*tasks, return_exceptions=True)

            for sub, resp in zip(subreddits, responses):
                if isinstance(resp, Exception):
                    logger.warning(f"Reddit {sub} error: {resp}")
                    continue

                try:
                    data = resp.json()
                    for post in data.get("data", {}).get("children", []):
                        p = post.get("data", {})
                        if p.get("stickied"):
                            continue

                        articles.append({
                            "title": p.get("title", ""),
                            "url": p.get("url", ""),
                            "source_name": f"Reddit r/{sub}",
                            "source_type": "discussion",
                            "published_at": datetime.fromtimestamp(p.get("created_utc", 0), tz=timezone.utc),
                            "summary": f"Score: {p.get('score', 0)} | Comments: {p.get('num_comments', 0)}",
                            "author": p.get("author"),
                            "is_verified": False,
                        })

                except Exception as e:
                    logger.warning(f"Reddit {sub} parse error: {e}")

        logger.info(f"Reddit: {len(articles)} articles")
        return articles[:limit]

    async def fetch_newsapi(self, limit: int = 20) -> List[Dict[str, Any]]:
        """从 NewsAPI 抓取"""
        if not self.api_key:
            return []

        articles = []
        params = {
            "q": "AI OR ChatGPT OR GPT OR LLM OR OpenAI OR Anthropic OR Claude OR Gemini",
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": min(limit, 100),
            "apiKey": self.api_key
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                resp = await client.get(f"{self.news_api_url}/everything", params=params)
                data = resp.json()

                if data.get("status") == "ok":
                    for a in data.get("articles", []):
                        published_at = a.get("publishedAt")
                        if published_at:
                            try:
                                published_at = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
                            except:
                                published_at = datetime.now(timezone.utc)
                        else:
                            published_at = datetime.now(timezone.utc)

                        articles.append({
                            "title": a.get("title", ""),
                            "url": a.get("url", ""),
                            "source_name": a.get("source", {}).get("name", "Unknown"),
                            "source_type": "news",
                            "published_at": published_at,
                            "summary": a.get("description", ""),
                            "author": a.get("author"),
                            "image_url": a.get("urlToImage"),
                            "is_verified": False,
                        })

                logger.info(f"NewsAPI: {len(articles)} articles")

            except Exception as e:
                logger.error(f"NewsAPI error: {e}")

        return articles

    async def create_news_records(self, articles: List[Dict[str, Any]]) -> List[int]:
        """
        创建 News 记录

        Args:
            articles: 文章列表

        Returns:
            创建的 news_id 列表
        """
        db = SessionLocal()
        created_ids = []

        try:
            for article in articles:
                url = article.get("url", "")
                title = article.get("title", "")

                if not url or not title:
                    continue

                external_id = self.generate_external_id(url, title)

                # 检查是否已存在
                existing = db.query(News).filter(News.external_id == external_id).first()
                if existing:
                    continue

                # 创建新记录
                news = News(
                    external_id=external_id,
                    title=title[:512],
                    source_name=article.get("source_name", "Unknown")[:128],
                    source_url=url[:1024],
                    author=article.get("author", "")[:256] if article.get("author") else None,
                    summary=article.get("summary", "")[:2000] if article.get("summary") else None,
                    image_url=article.get("image_url", "")[:1024] if article.get("image_url") else None,
                    published_at=article.get("published_at") or datetime.now(timezone.utc),
                    source_type=article.get("source_type", "news"),
                    processing_status="created",
                    visibility_status="inactive",
                )

                db.add(news)
                db.flush()
                created_ids.append(news.id)

            db.commit()
            logger.info(f"Created {len(created_ids)} news records")

        except Exception as e:
            db.rollback()
            logger.error(f"Create news records error: {e}")
        finally:
            db.close()

        return created_ids

    def _parse_feed_time(self, entry) -> datetime:
        """解析 RSS feed 时间"""
        if hasattr(entry, 'published_parsed') and entry.published_parsed:
            try:
                return datetime.fromtimestamp(mktime(entry.published_parsed), tz=timezone.utc)
            except:
                pass
        if hasattr(entry, 'updated_parsed') and entry.updated_parsed:
            try:
                return datetime.fromtimestamp(mktime(entry.updated_parsed), tz=timezone.utc)
            except:
                pass
        return datetime.now(timezone.utc)


# 全局单例
basic_fetcher = BasicFetcherService()
