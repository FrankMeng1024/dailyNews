import httpx
import hashlib
import asyncio
import feedparser
import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta, timezone
from time import mktime
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from bs4 import BeautifulSoup
import re

from app.config import settings
from app.models.news import News
from app.services.glm_service import glm_service
from app.services.fetch_coordinator import FetchCoordinator
from app.services.quality_scorer import quality_scorer
from app.services.config_service import ConfigService, DEFAULT_CONFIG
from app.utils.datetime_utils import parse_datetime_safe, ensure_utc, calculate_next_retry_time
from app.config_sources.source_config import (
    get_source_authority,
    get_fetch_limit,
    MIN_QUALITY_SCORE_ARCHIVE
)

logger = logging.getLogger(__name__)

# Import AI sources configuration
try:
    from app.config_sources.ai_sources import VERIFIED_AI_SOURCES, AI_KEYWORDS
except ImportError:
    VERIFIED_AI_SOURCES = {}
    AI_KEYWORDS = []


class NewsFetcher:
    """Multi-source AI news fetcher with GLM content generation"""

    def __init__(self):
        self.api_key = settings.NEWS_API_KEY
        self.glm_key = settings.GLM_API_KEY
        self.base_url = settings.NEWS_API_URL

    # ========== Web Scraping ==========

    def is_ai_related(self, text: str) -> bool:
        """Check if content is AI-related using keyword matching"""
        if not text or not AI_KEYWORDS:
            return True  # Default to True if no keywords configured

        text_lower = text.lower()
        # Check if any AI keyword appears in the text
        return any(keyword in text_lower for keyword in AI_KEYWORDS)

    async def verify_ai_relevance_with_glm(self, title: str, content: str) -> Tuple[bool, float]:
        """Use GLM to verify if content is truly AI-related and get relevance score

        Returns:
            (is_ai_related, relevance_score)
        """
        if not self.glm_key:
            # Fallback to keyword matching
            is_related = self.is_ai_related(f"{title} {content}")
            return (is_related, 0.7 if is_related else 0.3)

        prompt = f"""请判断以下内容是否与人工智能(AI)相关。

标题：{title}
内容摘要：{content[:500]}

要求：
1. 判断是否真正与AI相关（不是仅仅提到AI，而是核心内容就是关于AI的）
2. 给出相关性评分（0-10分，10分表示高度相关）

返回JSON格式：
{{"is_ai_related": true/false, "relevance_score": 8, "reason": "简短理由"}}

只返回JSON。"""

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    "https://open.bigmodel.cn/api/paas/v4/chat/completions",
                    headers={"Authorization": f"Bearer {self.glm_key}", "Content-Type": "application/json"},
                    json={
                        "model": "glm-4-flash",
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.1,
                        "max_tokens": 200
                    }
                )

                result = resp.json()
                if "error" in result:
                    # Fallback to keyword matching
                    is_related = self.is_ai_related(f"{title} {content}")
                    return (is_related, 0.7 if is_related else 0.3)

                content_text = result.get("choices", [{}])[0].get("message", {}).get("content", "")

                # Parse JSON response
                import json
                json_match = re.search(r'\{[\s\S]*\}', content_text)
                if json_match:
                    analysis = json.loads(json_match.group())
                    is_related = analysis.get("is_ai_related", False)
                    score = analysis.get("relevance_score", 5) / 10.0
                    logger.info(f"GLM AI relevance check: {is_related}, score: {score}, reason: {analysis.get('reason', '')}")
                    return (is_related, score)

        except Exception as e:
            logger.error(f"GLM verification error: {e}")

        # Fallback to keyword matching
        is_related = self.is_ai_related(f"{title} {content}")
        return (is_related, 0.7 if is_related else 0.3)

    # ========== Scheduled Fetch (Time-Window Based) ==========

    async def scheduled_fetch(
        self,
        db: Session,
        fetch_type: str = "all",
        custom_since: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Scheduled fetch with time-window and quality filtering

        This is the main entry point for scheduled/cron-based fetching

        Args:
            db: Database session
            fetch_type: Type of fetch (all/rss/newsapi)
            custom_since: Custom start time (overrides last_fetch_time)

        Returns:
            Dict with statistics
        """
        coordinator = FetchCoordinator(db)

        # Create fetch history record
        fetch_record = coordinator.create_fetch_record(
            fetch_type=fetch_type,
            source_name="all"
        )

        try:
            # Get time window
            time_window = coordinator.get_fetch_time_window(
                fetch_type=fetch_type,
                custom_since=custom_since
            )

            logger.info(f"=" * 80)
            logger.info(f"SCHEDULED FETCH STARTED")
            logger.info(f"Type: {fetch_type}")
            logger.info(f"Time window: {time_window['overlap_start']} → {time_window['end']}")
            logger.info(f"=" * 80)

            # Fetch from sources with time filtering
            all_articles = []

            if fetch_type in ["all", "rss"]:
                rss_articles = await self.fetch_rss_feeds(
                    since=time_window['overlap_start'],
                    until=time_window['end']
                )
                all_articles.extend(rss_articles)

            if fetch_type in ["all", "newsapi"]:
                newsapi_articles = await self.fetch_newsapi_ai(page_size=30)
                # Filter by time window
                newsapi_articles = coordinator.filter_by_time_window(
                    newsapi_articles,
                    time_window
                )
                all_articles.extend(newsapi_articles)

            # Also fetch HN and Reddit (always included in "all")
            if fetch_type == "all":
                hn_articles = await self.fetch_hackernews_ai(limit=15)
                reddit_articles = await self.fetch_reddit_ai(limit=15)

                # Filter by time window
                hn_articles = coordinator.filter_by_time_window(hn_articles, time_window)
                reddit_articles = coordinator.filter_by_time_window(reddit_articles, time_window)

                all_articles.extend(hn_articles)
                all_articles.extend(reddit_articles)

            logger.info(f"\nTotal articles fetched: {len(all_articles)}")

            if not all_articles:
                fetch_record.mark_completed(0, 0, 0)
                db.commit()  # Commit the status update
                return {
                    'success': True,
                    'articles_found': 0,
                    'articles_new': 0,
                    'articles_filtered': 0
                }

            # Scrape full content
            logger.info("Scraping article content...")
            scraped_contents = await self._scrape_articles_batch(all_articles)

            # Update articles with scraped content
            for i, content in enumerate(scraped_contents):
                if content:
                    all_articles[i]["scraped_content"] = content

            # Save with quality scoring and deduplication
            saved_count, skipped_count, saved_ids, filtered_count = await self._save_articles_with_quality_scoring(
                db,
                all_articles,
                coordinator
            )

            # Translate titles for saved news
            if saved_ids:
                await self._translate_titles_for_news(db, saved_ids)

            # Update last fetch time
            coordinator.update_last_fetch_time(
                time_window['end'],
                fetch_type=fetch_type
            )

            # Mark fetch as completed
            fetch_record.mark_completed(
                articles_found=len(all_articles),
                articles_new=saved_count,
                articles_filtered=filtered_count
            )
            db.commit()  # Commit the status update

            # Calculate and save quality thresholds based on actual score distribution
            try:
                from app.services.quality_threshold_manager import QualityThresholdManager
                thresholds = QualityThresholdManager.calculate_thresholds(db)
                QualityThresholdManager.save_thresholds(db, thresholds)
                logger.info(f"Updated quality thresholds: {thresholds}")
            except Exception as e:
                logger.info(f"Failed to update quality thresholds: {e}")

            logger.info(f"\n" + "=" * 80)
            logger.info(f"SCHEDULED FETCH COMPLETED")
            logger.info(f"Found: {len(all_articles)} | New: {saved_count} | Skipped: {skipped_count} | Filtered: {filtered_count}")
            logger.info(f"=" * 80)

            return {
                'success': True,
                'articles_found': len(all_articles),
                'articles_new': saved_count,
                'articles_skipped': skipped_count,
                'articles_filtered': filtered_count,
                'saved_ids': saved_ids
            }

        except Exception as e:
            import traceback
            error_msg = f"{str(e)}\n{traceback.format_exc()}"
            logger.info(f"Scheduled fetch error: {error_msg}")
            fetch_record.mark_failed(error_msg[:500])
            db.commit()  # Commit the status update
            return {
                'success': False,
                'error': str(e)
            }

    async def _scrape_articles_batch(self, articles: List[Dict[str, Any]]) -> List[Optional[str]]:
        """Scrape article content in batches"""
        scrape_tasks = [self.scrape_article_content(a.get("url", "")) for a in articles]
        image_tasks = [self.extract_image_url(a.get("url", "")) for a in articles]

        scraped_contents = []
        image_urls = []
        batch_size = 5

        # Scrape content
        for i in range(0, len(scrape_tasks), batch_size):
            batch = scrape_tasks[i:i + batch_size]
            results = await asyncio.gather(*batch, return_exceptions=True)
            for r in results:
                if isinstance(r, Exception):
                    scraped_contents.append(None)
                else:
                    scraped_contents.append(r)

        # Extract images
        for i in range(0, len(image_tasks), batch_size):
            batch = image_tasks[i:i + batch_size]
            results = await asyncio.gather(*batch, return_exceptions=True)
            for r in results:
                if isinstance(r, Exception):
                    image_urls.append(None)
                else:
                    image_urls.append(r)

        # Update articles with both content and images
        for i, (content, image_url) in enumerate(zip(scraped_contents, image_urls)):
            if content:
                articles[i]["scraped_content"] = content
            if image_url:
                articles[i]["image_url"] = image_url

        return scraped_contents

    async def _save_articles_with_quality_scoring(
        self,
        db: Session,
        articles: List[Dict[str, Any]],
        coordinator: FetchCoordinator
    ) -> Tuple[int, int, List[int], int]:
        """
        Save articles with quality scoring and filtering

        Returns:
            (saved_count, skipped_count, saved_ids, filtered_count)
        """
        saved_count = 0
        skipped_count = 0
        filtered_count = 0
        saved_ids = []

        for article in articles:
            external_id = self.generate_external_id(article)

            # Check for duplicates (with time-window dedup)
            published_at_obj = article.get('published_at')
            if isinstance(published_at_obj, str):
                try:
                    published_at_obj = datetime.fromisoformat(published_at_obj.replace("Z", "+00:00"))
                except:
                    published_at_obj = datetime.now(timezone.utc)

            if coordinator.is_duplicate(external_id, published_at_obj):
                skipped_count += 1
                continue

            # Extract content
            description = article.get("description", "")
            scraped_content = article.get("scraped_content")
            is_metadata_only = description.startswith("Score:") and "Comments:" in description

            # Determine original_content
            if scraped_content:
                original_content = scraped_content
            elif not is_metadata_only and description and len(description) > 50:
                original_content = description
            else:
                original_content = None

            # Allow ALL articles through - quality filtering happens at display time
            # Provide placeholder content if needed
            if not original_content:
                original_content = description if description else f"[No content] {article.get('title', '')}"

            # Parse published_at
            published_at = article.get("publishedAt")
            try:
                if published_at:
                    published_at = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
                else:
                    published_at = datetime.now(timezone.utc)
            except:
                published_at = datetime.now(timezone.utc)

            # Ensure timezone aware
            if not published_at.tzinfo:
                published_at = published_at.replace(tzinfo=timezone.utc)

            # Create news object
            source_type = article.get("source_type", "news")
            is_verified = article.get("is_verified", False)

            news = News(
                external_id=external_id,
                title=article.get("title", "")[:512],
                source_name=article.get("source", "Unknown")[:128],
                source_url=article.get("url", "")[:1024],
                author=article.get("author", "")[:256] if article.get("author") else None,
                content=None,  # GLM content generated later
                original_content=original_content,
                content_status="pending",
                summary=None if is_metadata_only else (description[:500] if description else None),
                image_url=article.get("image_url", "")[:1024] if article.get("image_url") else None,
                published_at=published_at,
                category="ai",
                source_type=source_type,
                content_format="text",
                is_verified=is_verified,
                ai_relevance_score=0.7 if is_verified else 0.5
            )

            # Calculate quality scores
            quality_scorer.calculate_comprehensive_score(news)

            # Quality score calculated but NOT used for filtering during save
            # All articles saved to database - filtering happens at display time based on user preference

            # Save to database
            db.add(news)
            db.flush()
            saved_ids.append(news.id)
            saved_count += 1

            logger.info(f"Saved (quality={news.final_score:.2f}, tier={news.source_tier}): {news.title[:50]}...")

        db.commit()
        return (saved_count, skipped_count, saved_ids, filtered_count)

    # ========== RSS Validation ==========
    def _validate_rss_feed(self, feed, source_name: str) -> bool:
        """验证 RSS feed 格式

        Args:
            feed: feedparser 解析的 feed 对象
            source_name: 源名称（用于日志）

        Returns:
            True 如果 feed 有效
        """
        # 检查 feedparser 的错误标志
        if feed.bozo:
            logger.warning(f"RSS parse warning for {source_name}: {feed.bozo_exception}")

        # 检查是否有 entries 属性
        if not hasattr(feed, 'entries'):
            logger.error(f"Invalid RSS for {source_name}: no entries attribute")
            return False

        # 空 feed 是有效的
        if not feed.entries:
            logger.info(f"RSS feed is empty for {source_name}")
            return True

        # 验证第一个条目的基本结构
        first = feed.entries[0]
        required = ['title', 'link']
        for field in required:
            if not hasattr(first, field):
                logger.warning(f"RSS entry missing required field '{field}' for {source_name}")

        return True

    # ========== RSS Feeds ==========
    async def fetch_rss_feeds(
        self,
        limit_per_source: Optional[int] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """Fetch articles from verified RSS feeds with time-window filtering

        Args:
            limit_per_source: Max articles per source (None for tier-based limits)
            since: Fetch articles published after this time (UTC)
            until: Fetch articles published before this time (UTC)

        Returns:
            List of articles with verified sources
        """
        if not VERIFIED_AI_SOURCES:
            logger.info("No verified AI sources configured")
            return []

        articles = []
        scrape_timeout = DEFAULT_CONFIG["scrape_timeout"]

        for source_id, source_info in VERIFIED_AI_SOURCES.items():
            # Skip sources without RSS URL (API-based sources)
            if "rss_url" not in source_info:
                continue

            # Get tier-based limit if not specified
            source_authority = get_source_authority(source_info["name"])
            tier = source_authority['tier']
            max_articles = limit_per_source if limit_per_source is not None else get_fetch_limit(tier)

            try:
                logger.info(f"Fetching RSS from {source_info['name']} (Tier {tier}, limit={max_articles})...")

                # Fetch RSS feed
                async with httpx.AsyncClient(timeout=float(scrape_timeout), follow_redirects=True) as client:
                    response = await client.get(source_info["rss_url"])

                    if response.status_code != 200:
                        logger.warning(f"Failed to fetch {source_info['name']}: HTTP {response.status_code}")
                        continue

                    # Parse RSS feed
                    feed = feedparser.parse(response.text)

                    # 验证 RSS feed
                    if not self._validate_rss_feed(feed, source_info['name']):
                        continue

                    if not feed.entries:
                        continue

                    # Process entries with time filtering
                    source_articles = []
                    for entry in feed.entries:
                        # Extract published date (timezone-aware)
                        published_at = None
                        if hasattr(entry, 'published_parsed') and entry.published_parsed:
                            try:
                                timestamp = mktime(entry.published_parsed)
                                published_at = datetime.fromtimestamp(timestamp, tz=timezone.utc)
                            except (ValueError, OverflowError) as e:
                                logger.warning(f"Invalid published_parsed for {source_info['name']}: {e}")
                                published_at = datetime.now(timezone.utc)
                        elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                            try:
                                timestamp = mktime(entry.updated_parsed)
                                published_at = datetime.fromtimestamp(timestamp, tz=timezone.utc)
                            except (ValueError, OverflowError) as e:
                                logger.warning(f"Invalid updated_parsed for {source_info['name']}: {e}")
                                published_at = datetime.now(timezone.utc)
                        else:
                            published_at = datetime.now(timezone.utc)

                        # Time-window filtering
                        if since and published_at < since:
                            continue
                        if until and published_at > until:
                            continue

                        # Extract content
                        description = ""
                        if hasattr(entry, 'summary'):
                            description = entry.summary
                        elif hasattr(entry, 'description'):
                            description = entry.description

                        # Clean HTML from description
                        if description:
                            soup = BeautifulSoup(description, 'html.parser')
                            description = soup.get_text(strip=True)

                        article = {
                            "title": entry.title if hasattr(entry, 'title') else "Untitled",
                            "url": entry.link if hasattr(entry, 'link') else "",
                            "source": source_info["name"],
                            "source_type": source_info["type"],
                            "publishedAt": published_at.isoformat(),
                            "description": description,
                            "is_verified": source_info["verified"],
                            "author": entry.author if hasattr(entry, 'author') else None,
                            "published_at": published_at  # Keep datetime object
                        }

                        source_articles.append(article)

                        # Check tier-based limit
                        if max_articles and len(source_articles) >= max_articles:
                            break

                    # Add to main list
                    articles.extend(source_articles)
                    logger.info(f"  ✓ Fetched {len(source_articles)} articles from {source_info['name']}")

            except httpx.TimeoutException:
                logger.warning(f"Timeout fetching RSS from {source_info['name']}")
                continue
            except httpx.RequestError as e:
                logger.warning(f"Request error fetching {source_info['name']}: {e}")
                continue
            except Exception as e:
                logger.error(f"Error fetching {source_info['name']}: {type(e).__name__}: {e}")
                continue

        logger.info(f"Total RSS articles fetched: {len(articles)}")
        return articles

    # ========== Web Scraping ==========

    async def scrape_article_content(self, url: str, db: Session = None) -> Optional[str]:
        """Scrape full article content from URL

        Args:
            url: Article URL
            db: Database session for config (optional, uses defaults if not provided)
        """
        if not url or url.startswith("https://news.ycombinator.com"):
            return None  # HN discussion pages don't have article content

        # 从配置获取参数
        scrape_timeout = DEFAULT_CONFIG["scrape_timeout"]
        min_para_len = DEFAULT_CONFIG["min_paragraph_length"]
        min_fallback_para_len = DEFAULT_CONFIG["min_fallback_paragraph_length"]
        min_paras_fallback = DEFAULT_CONFIG["min_paragraphs_for_fallback"]
        max_content = DEFAULT_CONFIG["max_content_for_scrape"]
        min_content_len = DEFAULT_CONFIG["min_content_length"]

        if db:
            scrape_timeout = ConfigService.get(db, "scrape_timeout", scrape_timeout)
            min_para_len = ConfigService.get(db, "min_paragraph_length", min_para_len)
            min_fallback_para_len = ConfigService.get(db, "min_fallback_paragraph_length", min_fallback_para_len)
            min_paras_fallback = ConfigService.get(db, "min_paragraphs_for_fallback", min_paras_fallback)
            max_content = ConfigService.get(db, "max_content_for_scrape", max_content)
            min_content_len = ConfigService.get(db, "min_content_length", min_content_len)

        try:
            async with httpx.AsyncClient(timeout=float(scrape_timeout), follow_redirects=True) as client:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7"
                }
                resp = await client.get(url, headers=headers)

                if resp.status_code != 200:
                    logger.warning(f"Scrape failed for {url[:50]}: HTTP {resp.status_code}")
                    return None

                soup = BeautifulSoup(resp.text, 'html.parser')

                # Remove unwanted elements
                for tag in soup.find_all(['script', 'style', 'nav', 'header', 'footer',
                                          'aside', 'iframe', 'noscript', 'form']):
                    tag.decompose()

                # Try to find article content using common selectors
                content = None
                selectors = [
                    'article',
                    '[role="main"]',
                    '.article-content',
                    '.post-content',
                    '.entry-content',
                    '.content-body',
                    '.story-body',
                    'main',
                    '.main-content',
                    '#content',
                ]

                for selector in selectors:
                    element = soup.select_one(selector)
                    if element:
                        # Get all paragraphs
                        paragraphs = element.find_all('p')
                        if paragraphs:
                            texts = []
                            for p in paragraphs:
                                text = p.get_text(strip=True)
                                if len(text) > min_para_len:
                                    texts.append(text)
                            if texts:
                                content = '\n\n'.join(texts)
                                break

                # Fallback: get all paragraphs from body
                if not content:
                    paragraphs = soup.find_all('p')
                    texts = []
                    for p in paragraphs:
                        text = p.get_text(strip=True)
                        if len(text) > min_fallback_para_len:
                            texts.append(text)
                    if len(texts) >= min_paras_fallback:
                        content = '\n\n'.join(texts[:20])  # Limit to 20 paragraphs

                if content and len(content) > min_content_len:
                    # Truncate if too long
                    return content[:max_content] if len(content) > max_content else content

                return None

        except httpx.TimeoutException:
            logger.warning(f"Scrape timeout for {url[:50]}")
            return None
        except httpx.RequestError as e:
            logger.warning(f"Scrape request error for {url[:50]}: {e}")
            return None
        except Exception as e:
            logger.error(f"Scrape error for {url[:50]}: {type(e).__name__}: {e}")
            return None

    async def extract_image_url(self, url: str, db: Session = None) -> Optional[str]:
        """Extract featured image URL from article page"""
        if not url:
            return None

        image_timeout = DEFAULT_CONFIG["image_extract_timeout"]
        if db:
            image_timeout = ConfigService.get(db, "image_extract_timeout", image_timeout)

        try:
            async with httpx.AsyncClient(timeout=float(image_timeout), follow_redirects=True) as client:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                    "Accept": "text/html,application/xhtml+xml"
                }
                resp = await client.get(url, headers=headers)

                if resp.status_code != 200:
                    return None

                soup = BeautifulSoup(resp.text, 'html.parser')

                # Try multiple strategies to find the main image
                # 1. Open Graph image
                og_image = soup.find('meta', property='og:image')
                if og_image and og_image.get('content'):
                    return og_image['content']

                # 2. Twitter card image
                twitter_image = soup.find('meta', attrs={'name': 'twitter:image'})
                if twitter_image and twitter_image.get('content'):
                    return twitter_image['content']

                # 3. Article featured image
                article = soup.find('article')
                if article:
                    # Look for img with specific classes
                    img = article.find('img', class_=lambda x: x and any(
                        keyword in x.lower() for keyword in ['featured', 'hero', 'main', 'cover']
                    ))
                    if img and img.get('src'):
                        return img['src']

                    # First large image in article
                    img = article.find('img')
                    if img and img.get('src'):
                        return img['src']

                # 4. First img in main content
                main = soup.find(['main', '[role="main"]'])
                if main:
                    img = main.find('img')
                    if img and img.get('src'):
                        return img['src']

                return None

        except httpx.TimeoutException:
            logger.warning(f"Image extraction timeout for {url[:50]}")
            return None
        except httpx.RequestError as e:
            logger.warning(f"Image extraction request error for {url[:50]}: {e}")
            return None
        except Exception as e:
            logger.error(f"Image extraction error for {url[:50]}: {type(e).__name__}: {e}")
            return None

    # ========== News Sources ==========

    async def fetch_hackernews_ai(self, limit: int = 30) -> List[Dict[str, Any]]:
        """Fetch AI-related stories from Hacker News"""
        ai_keywords = ['ai', 'gpt', 'llm', 'openai', 'anthropic', 'claude', 'chatgpt',
                       'machine learning', 'neural', 'transformer', 'diffusion', 'gemini',
                       'mistral', 'llama', 'deepseek', 'artificial intelligence', 'deep learning']

        scrape_timeout = DEFAULT_CONFIG["scrape_timeout"]

        async with httpx.AsyncClient(timeout=float(scrape_timeout)) as client:
            try:
                resp = await client.get("https://hacker-news.firebaseio.com/v0/topstories.json")
                story_ids = resp.json()[:100]

                articles = []
                for story_id in story_ids:
                    if len(articles) >= limit:
                        break

                    story_resp = await client.get(f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json")
                    story = story_resp.json()

                    if not story or story.get("type") != "story":
                        continue

                    title = story.get("title", "").lower()
                    if any(kw in title for kw in ai_keywords):
                        articles.append({
                            "title": story.get("title", ""),
                            "url": story.get("url", f"https://news.ycombinator.com/item?id={story_id}"),
                            "source": "Hacker News",
                            "source_type": "discussion",
                            "publishedAt": datetime.fromtimestamp(story.get("time", 0), tz=timezone.utc).isoformat(),
                            "description": f"Score: {story.get('score', 0)} | Comments: {story.get('descendants', 0)}",
                            "hn_score": story.get("score", 0)
                        })
                return articles
            except Exception as e:
                logger.error(f"HackerNews error: {type(e).__name__}: {e}")
                return []

    async def fetch_reddit_ai(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Fetch from Reddit AI subreddits"""
        subreddits = ["MachineLearning", "artificial", "LocalLLaMA"]
        articles = []

        scrape_timeout = DEFAULT_CONFIG["scrape_timeout"]

        async with httpx.AsyncClient(timeout=float(scrape_timeout)) as client:
            for sub in subreddits:
                try:
                    resp = await client.get(
                        f"https://www.reddit.com/r/{sub}/hot.json?limit=15",
                        headers={"User-Agent": "AINewsBot/1.0"}
                    )
                    data = resp.json()

                    for post in data.get("data", {}).get("children", []):
                        p = post.get("data", {})
                        # 只过滤置顶帖，保留自发帖(is_self)
                        if p.get("stickied"):
                            continue

                        articles.append({
                            "title": p.get("title", ""),
                            "url": p.get("url", ""),
                            "source": f"Reddit r/{sub}",
                            "source_type": "discussion",
                            "publishedAt": datetime.fromtimestamp(p.get("created_utc", 0), tz=timezone.utc).isoformat(),
                            "description": f"Score: {p.get('score', 0)} | Comments: {p.get('num_comments', 0)}",
                            "reddit_score": p.get("score", 0)
                        })

                        if len(articles) >= limit:
                            break
                except Exception as e:
                    logger.info(f"Reddit {sub} error: {e}")
                    continue

        return articles[:limit]

    async def fetch_newsapi_ai(self, page_size: int = 30) -> List[Dict[str, Any]]:
        """Fetch from NewsAPI with AI search"""
        if not self.api_key or self.api_key == "your_newsapi_key_here":
            return []

        params = {
            "q": "AI OR ChatGPT OR GPT OR LLM OR OpenAI OR Anthropic OR Claude OR Gemini",
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": min(page_size, 100),
            "apiKey": self.api_key
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.get(f"{self.base_url}/everything", params=params)
                data = response.json()

                if data.get("status") == "ok":
                    return [{
                        "title": a.get("title", ""),
                        "url": a.get("url", ""),
                        "source": a.get("source", {}).get("name", "Unknown"),
                        "source_type": "news",
                        "publishedAt": a.get("publishedAt", ""),
                        "description": a.get("description", ""),
                    } for a in data.get("articles", [])]

                # Fallback to top-headlines
                params = {"country": "us", "category": "technology", "pageSize": page_size, "apiKey": self.api_key}
                response = await client.get(f"{self.base_url}/top-headlines", params=params)
                data = response.json()

                if data.get("status") == "ok":
                    return [{
                        "title": a.get("title", ""),
                        "url": a.get("url", ""),
                        "source": a.get("source", {}).get("name", "Unknown"),
                        "source_type": "news",
                        "publishedAt": a.get("publishedAt", ""),
                        "description": a.get("description", ""),
                    } for a in data.get("articles", [])]
                return []
            except Exception as e:
                logger.info(f"NewsAPI error: {e}")
                return []

    # ========== GLM Content Generation ==========

    async def glm_generate_content(self, articles: List[Dict[str, Any]], language: str = "zh") -> List[Dict[str, Any]]:
        """Use GLM to generate full content for each news article

        Args:
            articles: List of news articles
            language: 'zh' for Chinese, 'en' for English, 'bilingual' for both
        """
        if not self.glm_key or len(articles) == 0:
            logger.info("No GLM key or no articles")
            return articles

        # Process one article at a time for maximum quality
        batch_size = 1
        import json
        import re

        for batch_start in range(0, min(len(articles), 30), batch_size):
            batch = articles[batch_start:batch_start + batch_size]

            news_list = "\n".join([
                f"{i+1}. [{a.get('source', 'Unknown')}] {a.get('title', '')}"
                for i, a in enumerate(batch)
            ])

            # Choose prompt based on language
            if language == "en":
                prompt = f"""You are a senior tech journalist. Write comprehensive summaries for each AI news item.

Requirements:
- Adaptive length: Match the complexity and importance of the news. Simple news can be brief, complex news should be thorough.
- Clear structure:
  · Lead: One sentence capturing the core event (who, what, when)
  · Body: Technical/product details, key metrics and data
  · Context: Why it matters, industry background
  · Impact: Implications for users/industry/market
- Preserve specific numbers, percentages, and quotes from the original
- Separate paragraphs with blank lines, natural flow, no numbering

News list:
{news_list}

Return JSON:
{{"articles": [{{"id": 1, "content": "News summary content...", "score": 8, "ai_related": true}}]}}

Return only JSON."""
            else:  # zh or bilingual (default to Chinese)
                prompt = f"""你是资深科技记者，请为这条AI新闻撰写完整详尽的中文摘要。

核心要求：完整性优先
- 目标是保留原文50%以上的核心信息量，不是简短概括
- 所有重要细节、数据、观点都必须包含
- 宁可长一些也不要遗漏关键信息

内容结构：
1. 核心事件：谁、做了什么、什么时候、结果如何
2. 详细内容：技术细节、产品特性、具体数据、关键指标
3. 背景分析：为什么重要、行业背景、相关事件
4. 影响评估：对用户/行业/市场的具体影响
5. 引用保留：原文中的重要引语、声明必须保留

格式要求：
- 段落之间用空行分隔
- 自然流畅的叙述，无需编号
- 保留所有具体数字和百分比

新闻：
{news_list}

返回JSON：
{{"articles": [{{"id": 1, "content": "详尽的摘要内容...", "score": 8, "ai_related": true}}]}}

只返回JSON。"""

            try:
                async with httpx.AsyncClient(timeout=90.0) as client:
                    resp = await client.post(
                        "https://open.bigmodel.cn/api/paas/v4/chat/completions",
                        headers={"Authorization": f"Bearer {self.glm_key}", "Content-Type": "application/json"},
                        json={
                            "model": "glm-4-flash",
                            "messages": [{"role": "user", "content": prompt}],
                            "temperature": 0.3,
                            "max_tokens": 4096
                        }
                    )

                    result = resp.json()

                    if "error" in result:
                        logger.info(f"GLM API error: {result['error']}")
                        continue

                    content = result.get("choices", [{}])[0].get("message", {}).get("content", "")

                    # Parse JSON - clean control characters first
                    json_match = re.search(r'\{[\s\S]*\}', content)
                    if json_match:
                        try:
                            json_str = json_match.group()
                            # Remove ALL control characters and replace newlines in string values
                            # First, remove all control chars except structural whitespace
                            cleaned = re.sub(r'[\x00-\x1f\x7f-\x9f]', lambda m: ' ' if m.group() in '\n\r\t' else '', json_str)
                            # Replace actual newlines with escaped version for JSON
                            # But only inside string values (between quotes)
                            def escape_newlines_in_strings(s):
                                result = []
                                in_string = False
                                i = 0
                                while i < len(s):
                                    c = s[i]
                                    if c == '"' and (i == 0 or s[i-1] != '\\'):
                                        in_string = not in_string
                                        result.append(c)
                                    elif in_string and c == '\n':
                                        result.append(' ')  # Replace newline with space
                                    elif in_string and c == '\r':
                                        pass  # Skip carriage return
                                    elif in_string and c == '\t':
                                        result.append(' ')  # Replace tab with space
                                    else:
                                        result.append(c)
                                    i += 1
                                return ''.join(result)
                            cleaned = escape_newlines_in_strings(cleaned)
                            analysis = json.loads(cleaned)

                            for item in analysis.get("articles", []):
                                idx = item.get("id", 0) - 1
                                if 0 <= idx < len(batch):
                                    real_idx = batch_start + idx
                                    articles[real_idx]["generated_content"] = item.get("content", "")
                                    articles[real_idx]["glm_score"] = item.get("score", 5) / 10.0
                                    articles[real_idx]["ai_related"] = item.get("ai_related", True)
                                    logger.info(f"Generated content for: {articles[real_idx]['title'][:40]}...")
                        except json.JSONDecodeError as e:
                            logger.info(f"JSON parse error: {e}")
                    else:
                        logger.info(f"No JSON found in response: {content[:200]}")

            except Exception as e:
                logger.info(f"GLM batch error: {e}")
                import traceback
                traceback.print_exc()

        # Don't sort here - let API handle sorting by time
        return articles

    # ========== Main Fetch ==========

    def generate_external_id(self, article: Dict[str, Any]) -> str:
        url = article.get("url", "")
        return hashlib.md5(url.encode()).hexdigest()

    async def fetch_and_save_news(self, db: Session, page_size: int = 50, language: str = "zh", skip_glm: bool = True) -> int:
        """Fetch from all sources and save immediately, GLM runs async later

        Args:
            db: Database session
            page_size: Number of articles to fetch
            language: 'zh' for Chinese, 'en' for English
            skip_glm: Always True - GLM generation is async
        """

        # Fetch from all sources in parallel
        logger.info("Fetching from multiple sources...")

        # RSS feeds (new verified sources)
        rss_task = self.fetch_rss_feeds(limit_per_source=10)

        # Existing sources
        hn_task = self.fetch_hackernews_ai(limit=15)
        reddit_task = self.fetch_reddit_ai(limit=15)
        newsapi_task = self.fetch_newsapi_ai(page_size=20)

        rss_articles, hn_articles, reddit_articles, newsapi_articles = await asyncio.gather(
            rss_task, hn_task, reddit_task, newsapi_task
        )

        logger.info(f"Fetched: RSS={len(rss_articles)}, HN={len(hn_articles)}, Reddit={len(reddit_articles)}, NewsAPI={len(newsapi_articles)}")

        # Combine all articles
        all_articles = rss_articles + hn_articles + reddit_articles + newsapi_articles

        if not all_articles:
            logger.info("No articles fetched")
            return (0, 0, [])

        # Filter AI-related content using keyword matching (fast pre-filter)
        logger.info("Pre-filtering AI-related content...")
        ai_filtered_articles = []
        for article in all_articles:
            title = article.get("title", "")
            description = article.get("description", "")

            # Skip if already verified (from RSS sources)
            if article.get("is_verified", False):
                ai_filtered_articles.append(article)
                continue

            # Check AI relevance for non-verified sources
            if self.is_ai_related(f"{title} {description}"):
                ai_filtered_articles.append(article)
            else:
                logger.info(f"Filtered out (not AI-related): {title[:50]}...")

        logger.info(f"After AI filtering: {len(ai_filtered_articles)} articles")

        # Scrape full article content for each article (in parallel, limited concurrency)
        logger.info("Scraping article content...")
        scrape_tasks = []
        for article in ai_filtered_articles:
            url = article.get("url", "")
            scrape_tasks.append(self.scrape_article_content(url))

        # Run scraping with limited concurrency (5 at a time)
        scraped_contents = []
        batch_size = 5
        for i in range(0, len(scrape_tasks), batch_size):
            batch = scrape_tasks[i:i + batch_size]
            results = await asyncio.gather(*batch, return_exceptions=True)
            for r in results:
                if isinstance(r, Exception):
                    scraped_contents.append(None)
                else:
                    scraped_contents.append(r)

        # Update articles with scraped content
        for i, content in enumerate(scraped_contents):
            if content:
                ai_filtered_articles[i]["scraped_content"] = content
                logger.info(f"Scraped {len(content)} chars for: {ai_filtered_articles[i]['title'][:40]}...")

        # Save to database - only save articles with original content
        saved_count = 0
        skipped_count = 0
        no_content_count = 0
        saved_ids = []

        for article in ai_filtered_articles:
            external_id = self.generate_external_id(article)
            if db.query(News).filter(News.external_id == external_id).first():
                skipped_count += 1
                continue

            # Use scraped content if available, otherwise use description
            description = article.get("description", "")
            scraped_content = article.get("scraped_content")
            is_metadata_only = description.startswith("Score:") and "Comments:" in description

            # Determine original_content: prefer scraped, then description
            if scraped_content:
                original_content = scraped_content
            elif not is_metadata_only and description and len(description) > 50:
                original_content = description
            else:
                original_content = None

            # IMPORTANT: Save ALL articles, even if scraping failed
            # Failed articles will be visible in developer interface for retry
            # Use placeholder content if nothing available
            if not original_content:
                original_content = description if description else ""
                # Mark as needing scraping retry
                scraping_failed = True
            else:
                scraping_failed = len(original_content) < 200

            published_at = article.get("publishedAt")
            try:
                if published_at:
                    published_at = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
                else:
                    published_at = datetime.now(timezone.utc)
            except:
                published_at = datetime.now(timezone.utc)

            # Determine source type
            source_type = article.get("source_type", "news")
            is_verified = article.get("is_verified", False)

            news = News(
                external_id=external_id,
                title=article.get("title", "")[:512],
                source_name=article.get("source", "Unknown")[:128],
                source_url=article.get("url", "")[:1024],
                author=article.get("author", "")[:256] if article.get("author") else None,
                content=None,  # GLM content generated later
                original_content=original_content,
                content_status="pending",
                summary=None if is_metadata_only else (description[:500] if description else None),
                image_url=article.get("image_url"),
                published_at=published_at,
                glm_score=0.5,
                final_score=0.5,
                category="ai",
                # New fields
                source_type=source_type,
                content_format="text",
                is_verified=is_verified,
                ai_relevance_score=0.7 if is_verified else None,  # Will be updated by GLM later
                # Scraping status - mark if scraping failed
                scraping_retry_count=1 if scraping_failed else 0,
                scraping_last_error="Content too short or missing" if scraping_failed else None
            )
            db.add(news)
            db.flush()
            saved_ids.append(news.id)
            saved_count += 1

            if scraping_failed:
                no_content_count += 1
                logger.info(f"Saved (scraping failed): {article.get('title', '')[:40]}...")
            else:
                logger.info(f"Saved: {article.get('title', '')[:40]}...")

        db.commit()
        logger.info(f"Saved {saved_count} new articles, skipped {skipped_count} duplicates, {no_content_count} need scraping retry")

        # Translate titles for saved news
        if saved_ids:
            await self._translate_titles_for_news(db, saved_ids)

        # Update quality thresholds based on new score distribution
        if saved_count > 0:
            try:
                from app.services.quality_threshold_manager import QualityThresholdManager
                thresholds = QualityThresholdManager.calculate_thresholds(db)
                QualityThresholdManager.save_thresholds(db, thresholds)
                logger.info(f"Updated quality thresholds: {thresholds}")
            except Exception as e:
                logger.info(f"Failed to update quality thresholds: {e}")

        return (saved_count, skipped_count, saved_ids, no_content_count)

    # Title translation retry intervals in minutes: 1, 3, 6, 9, 12
    TITLE_RETRY_INTERVALS = [1, 3, 6, 9, 12]
    TITLE_MAX_RETRIES = 5

    def _get_title_next_retry_time(self, retry_count: int) -> datetime:
        """Calculate next retry time for title translation"""
        if retry_count >= len(self.TITLE_RETRY_INTERVALS):
            interval = self.TITLE_RETRY_INTERVALS[-1]
        else:
            interval = self.TITLE_RETRY_INTERVALS[retry_count]
        return datetime.now(timezone.utc) + timedelta(minutes=interval)

    async def _translate_titles_for_news(self, db: Session, news_ids: List[int]) -> int:
        """Translate English titles to Chinese for saved news

        Sets title_status:
        - 'ready' if translation succeeds
        - 'pending' if translation fails (will be retried)
        - 'failed' if max retries reached

        Uses adaptive batch sizing: 8 -> 5 -> 1 on failures to handle rate limits.
        """
        news_list = db.query(News).filter(News.id.in_(news_ids)).all()
        if not news_list:
            return 0

        logger.info(f"Translating {len(news_list)} titles with adaptive batching...")

        total_success = 0
        batch_size = 8  # Start with 8 titles per batch

        i = 0
        while i < len(news_list):
            batch = news_list[i:i + batch_size]
            logger.info(f"  Translating {len(batch)} titles (batch_size={batch_size})...")

            success, failed_news = await self._translate_batch_with_fallback(db, batch, batch_size)
            total_success += success

            if failed_news and batch_size > 1:
                # Retry failed items with smaller batch size
                retry_size = 5 if batch_size == 8 else 1
                logger.info(f"  ↓ Retrying {len(failed_news)} failed items with batch_size={retry_size}...")

                retry_success, still_failed = await self._translate_batch_with_fallback(db, failed_news, retry_size)
                total_success += retry_success

                if still_failed and retry_size > 1:
                    # Final retry: one by one
                    logger.info(f"  ↓ Final retry: {len(still_failed)} items one by one...")
                    final_success, final_failed = await self._translate_batch_with_fallback(db, still_failed, 1)
                    total_success += final_success

                    # Mark truly failed items for retry queue
                    for news in final_failed:
                        news.title_retry_count = (news.title_retry_count or 0) + 1
                        if news.title_retry_count >= self.TITLE_MAX_RETRIES:
                            news.title_status = "failed"
                            news.title_last_error = "Max retries reached after adaptive fallback"
                        else:
                            news.title_status = "pending"
                            news.title_next_retry_at = self._get_title_next_retry_time(news.title_retry_count)
                        logger.info(f"    ✗ [{news.id}] Queued for retry, count={news.title_retry_count}")
                    db.commit()

            i += batch_size

            # Delay between batches
            if i < len(news_list):
                await asyncio.sleep(1)

        logger.info(f"Successfully translated {total_success}/{len(news_list)} titles")
        return total_success

    async def _translate_batch_with_fallback(
        self,
        db: Session,
        news_batch: List[News],
        batch_size: int
    ) -> tuple:
        """Translate a batch of news titles, returns (success_count, failed_news_list)"""
        success_count = 0
        failed_news = []

        for batch_start in range(0, len(news_batch), batch_size):
            batch = news_batch[batch_start:batch_start + batch_size]

            try:
                # Prepare data
                news_items = [
                    {
                        "title": n.title,
                        "content": n.original_content or n.summary or ""
                    }
                    for n in batch
                ]

                # Call translation API
                translated = await glm_service.translate_titles_with_context(news_items)

                # Process results
                for j, news in enumerate(batch):
                    if j < len(translated) and translated[j] and translated[j] != news.title:
                        news.title_zh = translated[j]
                        news.title_status = "ready"
                        news.title_last_error = None
                        news.title_next_retry_at = None
                        success_count += 1
                        logger.info(f"    ✓ [{news.id}] {news.title[:30]}... → {translated[j]}")
                    else:
                        failed_news.append(news)

                db.commit()

                # Small delay between sub-batches
                if batch_start + batch_size < len(news_batch):
                    await asyncio.sleep(0.5)

            except Exception as e:
                error_type = type(e).__name__
                is_rate_limit = "429" in str(e) or "rate" in str(e).lower()
                logger.info(f"    ⚠ Batch error ({error_type}): {str(e)[:80]}")

                # Add all items in this batch to failed list
                failed_news.extend(batch)

                # Longer delay on rate limit
                if is_rate_limit:
                    await asyncio.sleep(3)
                else:
                    await asyncio.sleep(1)

        return success_count, failed_news

    # Retry intervals in minutes: 1, 3, 6, 9, 12
    RETRY_INTERVALS = [1, 3, 6, 9, 12]
    MAX_RETRIES = 5

    def _is_retryable_error(self, error: Exception) -> bool:
        """Check if error is retryable (connection/timeout issues)"""
        error_str = str(error).lower()
        retryable_keywords = ['timeout', 'connection', 'connect', 'network', 'reset', 'refused', 'unavailable']
        return any(kw in error_str for kw in retryable_keywords)

    def _get_next_retry_time(self, retry_count: int) -> datetime:
        """Calculate next retry time based on retry count"""
        if retry_count >= len(self.RETRY_INTERVALS):
            interval = self.RETRY_INTERVALS[-1]
        else:
            interval = self.RETRY_INTERVALS[retry_count]
        return datetime.now(timezone.utc) + timedelta(minutes=interval)

    async def generate_content_for_news(self, db: Session, news_ids: List[int], language: str = "zh") -> int:
        """Generate GLM content for specific news items (async background task)"""
        if not self.glm_key:
            logger.info("No GLM key configured")
            return 0

        import json

        generated_count = 0

        for news_id in news_ids:
            news = db.query(News).filter(News.id == news_id).first()
            if not news or news.content_status == "ready":
                continue

            # Skip if max retries reached
            if news.glm_retry_count >= self.MAX_RETRIES:
                if news.content_status != "failed":
                    news.content_status = "failed"
                    db.commit()
                continue

            # Mark as generating
            news.content_status = "generating"
            db.commit()

            # Prepare prompt with title + original_content
            news_info = f"标题: {news.title}\n来源: {news.source_name}"
            if news.original_content:
                # Truncate to 4000 chars for prompt
                content_preview = news.original_content[:4000]
                news_info += f"\n\n原文内容:\n{content_preview}"

            prompt = f"""你是资深科技记者。请根据以下新闻内容，撰写一篇结构清晰、段落分明的中文摘要。

要求：
1. 分段落撰写，每段聚焦一个主题
2. 段落之间用空行分隔
3. 语言通俗易懂，避免晦涩术语
4. 保留关键数据、时间、人名等具体信息
5. 不要遗漏重要内容，也不要重复表述
6. 总字数300-600字

结构建议：
- 第一段：核心事件概述（谁做了什么，结果如何）
- 第二段：详细内容（技术细节、产品特性、具体数据）
- 第三段：背景与意义（为什么重要，行业影响）
- 第四段：展望（如有后续计划或市场预期）

{news_info}

请直接输出摘要内容，不需要JSON格式，不需要标题。"""

            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    resp = await client.post(
                        "https://open.bigmodel.cn/api/paas/v4/chat/completions",
                        headers={"Authorization": f"Bearer {self.glm_key}", "Content-Type": "application/json"},
                        json={
                            "model": "glm-4-flash",
                            "messages": [{"role": "user", "content": prompt}],
                            "temperature": 0.3,
                            "max_tokens": 2048
                        }
                    )

                    result = resp.json()
                    if "error" in result:
                        error_msg = str(result['error'])
                        logger.info(f"GLM API error for news {news_id}: {error_msg}")
                        # API errors are usually not retryable (rate limit, invalid key, etc.)
                        news.content_status = "pending"
                        news.glm_last_error = error_msg[:500]
                        news.glm_retry_count = (news.glm_retry_count or 0) + 1
                        news.glm_next_retry_at = self._get_next_retry_time(news.glm_retry_count)
                        db.commit()
                        continue

                    content = result.get("choices", [{}])[0].get("message", {}).get("content", "")

                    if content and len(content) > 50:
                        # Success - clean up the content
                        content = content.strip()
                        news.content = content
                        news.glm_score = 0.7
                        news.content_status = "ready"
                        news.glm_last_error = None
                        news.glm_next_retry_at = None
                        db.commit()
                        generated_count += 1
                        logger.info(f"Generated content for news {news_id}: {news.title[:40]}...")
                    else:
                        # Empty response - mark as failed (not retryable)
                        news.content_status = "failed"
                        news.glm_last_error = "Empty or too short response from GLM"
                        db.commit()

            except Exception as e:
                error_msg = str(e)
                logger.info(f"GLM error for news {news_id}: {error_msg}")

                # Check if error is retryable
                if self._is_retryable_error(e):
                    news.content_status = "pending"
                    news.glm_last_error = error_msg[:500]
                    news.glm_retry_count = (news.glm_retry_count or 0) + 1
                    news.glm_next_retry_at = self._get_next_retry_time(news.glm_retry_count)
                    logger.info(f"Retryable error, scheduled retry #{news.glm_retry_count} at {news.glm_next_retry_at}")
                else:
                    # Non-retryable error
                    news.content_status = "failed"
                    news.glm_last_error = error_msg[:500]

                db.commit()

            await asyncio.sleep(0.5)

        return generated_count


news_fetcher = NewsFetcher()
