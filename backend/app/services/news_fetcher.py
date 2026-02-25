import httpx
import hashlib
import asyncio
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from bs4 import BeautifulSoup
import re

from app.config import settings
from app.models.news import News
from app.services.glm_service import glm_service


class NewsFetcher:
    """Multi-source AI news fetcher with GLM content generation"""

    def __init__(self):
        self.api_key = settings.NEWS_API_KEY
        self.glm_key = settings.GLM_API_KEY
        self.base_url = settings.NEWS_API_URL

    # ========== Web Scraping ==========

    async def scrape_article_content(self, url: str) -> Optional[str]:
        """Scrape full article content from URL"""
        if not url or url.startswith("https://news.ycombinator.com"):
            return None  # HN discussion pages don't have article content

        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7"
                }
                resp = await client.get(url, headers=headers)

                if resp.status_code != 200:
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
                                if len(text) > 30:  # Filter out short fragments
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
                        if len(text) > 50:  # More strict for fallback
                            texts.append(text)
                    if len(texts) >= 3:  # Need at least 3 paragraphs
                        content = '\n\n'.join(texts[:20])  # Limit to 20 paragraphs

                if content and len(content) > 200:
                    # Truncate if too long (keep first 8000 chars)
                    return content[:8000] if len(content) > 8000 else content

                return None

        except Exception as e:
            print(f"Scrape error for {url[:50]}: {e}")
            return None

    # ========== News Sources ==========

    async def fetch_hackernews_ai(self, limit: int = 30) -> List[Dict[str, Any]]:
        """Fetch AI-related stories from Hacker News"""
        ai_keywords = ['ai', 'gpt', 'llm', 'openai', 'anthropic', 'claude', 'chatgpt',
                       'machine learning', 'neural', 'transformer', 'diffusion', 'gemini',
                       'mistral', 'llama', 'deepseek', 'artificial intelligence', 'deep learning']

        async with httpx.AsyncClient(timeout=30.0) as client:
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
                            "publishedAt": datetime.utcfromtimestamp(story.get("time", 0)).isoformat(),
                            "description": f"Score: {story.get('score', 0)} | Comments: {story.get('descendants', 0)}",
                            "hn_score": story.get("score", 0)
                        })
                return articles
            except Exception as e:
                print(f"HackerNews error: {e}")
                return []

    async def fetch_reddit_ai(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Fetch from Reddit AI subreddits"""
        subreddits = ["MachineLearning", "artificial", "LocalLLaMA"]
        articles = []

        async with httpx.AsyncClient(timeout=30.0) as client:
            for sub in subreddits:
                try:
                    resp = await client.get(
                        f"https://www.reddit.com/r/{sub}/hot.json?limit=15",
                        headers={"User-Agent": "AINewsBot/1.0"}
                    )
                    data = resp.json()

                    for post in data.get("data", {}).get("children", []):
                        p = post.get("data", {})
                        if p.get("stickied") or p.get("is_self"):
                            continue

                        articles.append({
                            "title": p.get("title", ""),
                            "url": p.get("url", ""),
                            "source": f"Reddit r/{sub}",
                            "publishedAt": datetime.utcfromtimestamp(p.get("created_utc", 0)).isoformat(),
                            "description": f"Score: {p.get('score', 0)} | Comments: {p.get('num_comments', 0)}",
                            "reddit_score": p.get("score", 0)
                        })

                        if len(articles) >= limit:
                            break
                except Exception as e:
                    print(f"Reddit {sub} error: {e}")
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
                        "publishedAt": a.get("publishedAt", ""),
                        "description": a.get("description", ""),
                    } for a in data.get("articles", [])]
                return []
            except Exception as e:
                print(f"NewsAPI error: {e}")
                return []

    # ========== GLM Content Generation ==========

    async def glm_generate_content(self, articles: List[Dict[str, Any]], language: str = "zh") -> List[Dict[str, Any]]:
        """Use GLM to generate full content for each news article

        Args:
            articles: List of news articles
            language: 'zh' for Chinese, 'en' for English, 'bilingual' for both
        """
        if not self.glm_key or len(articles) == 0:
            print("No GLM key or no articles")
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
                        print(f"GLM API error: {result['error']}")
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
                                    print(f"Generated content for: {articles[real_idx]['title'][:40]}...")
                        except json.JSONDecodeError as e:
                            print(f"JSON parse error: {e}")
                    else:
                        print(f"No JSON found in response: {content[:200]}")

            except Exception as e:
                print(f"GLM batch error: {e}")
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
        print("Fetching from multiple sources...")
        hn_task = self.fetch_hackernews_ai(limit=15)
        reddit_task = self.fetch_reddit_ai(limit=15)
        newsapi_task = self.fetch_newsapi_ai(page_size=20)

        hn_articles, reddit_articles, newsapi_articles = await asyncio.gather(
            hn_task, reddit_task, newsapi_task
        )

        print(f"Fetched: HN={len(hn_articles)}, Reddit={len(reddit_articles)}, NewsAPI={len(newsapi_articles)}")

        # Combine all articles
        all_articles = hn_articles + reddit_articles + newsapi_articles

        if not all_articles:
            print("No articles fetched")
            return (0, 0, [])

        # Scrape full article content for each article (in parallel, limited concurrency)
        print("Scraping article content...")
        scrape_tasks = []
        for article in all_articles:
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
                all_articles[i]["scraped_content"] = content
                print(f"Scraped {len(content)} chars for: {all_articles[i]['title'][:40]}...")

        # Save to database - only save articles with original content
        saved_count = 0
        skipped_count = 0
        no_content_count = 0
        saved_ids = []

        for article in all_articles:
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

            # Skip articles without original content
            if not original_content:
                no_content_count += 1
                print(f"Skipped (no content): {article.get('title', '')[:40]}...")
                continue

            published_at = article.get("publishedAt")
            try:
                if published_at:
                    published_at = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
                else:
                    published_at = datetime.utcnow()
            except:
                published_at = datetime.utcnow()

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
                image_url=None,
                published_at=published_at,
                glm_score=0.5,
                final_score=0.5,
                category="ai"
            )
            db.add(news)
            db.flush()
            saved_ids.append(news.id)
            saved_count += 1

        db.commit()
        print(f"Saved {saved_count} new articles, skipped {skipped_count} duplicates, {no_content_count} without content")

        # Translate titles for saved news
        if saved_ids:
            await self._translate_titles_for_news(db, saved_ids)

        return (saved_count, skipped_count, saved_ids, no_content_count)

    async def _translate_titles_for_news(self, db: Session, news_ids: List[int]) -> int:
        """Translate English titles to Chinese for saved news"""
        news_list = db.query(News).filter(News.id.in_(news_ids)).all()
        if not news_list:
            return 0

        # Get titles to translate
        titles = [n.title for n in news_list]
        print(f"Translating {len(titles)} titles...")

        try:
            # Batch translate
            translated = await glm_service.translate_titles_batch(titles)

            # Update news records
            for i, news in enumerate(news_list):
                if i < len(translated):
                    news.title_zh = translated[i]

            db.commit()
            print(f"Translated {len(translated)} titles")
            return len(translated)
        except Exception as e:
            print(f"Title translation error: {e}")
            return 0

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
        return datetime.utcnow() + timedelta(minutes=interval)

    async def generate_content_for_news(self, db: Session, news_ids: List[int], language: str = "zh") -> int:
        """Generate GLM content for specific news items (async background task)"""
        if not self.glm_key:
            print("No GLM key configured")
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
                        print(f"GLM API error for news {news_id}: {error_msg}")
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
                        print(f"Generated content for news {news_id}: {news.title[:40]}...")
                    else:
                        # Empty response - mark as failed (not retryable)
                        news.content_status = "failed"
                        news.glm_last_error = "Empty or too short response from GLM"
                        db.commit()

            except Exception as e:
                error_msg = str(e)
                print(f"GLM error for news {news_id}: {error_msg}")

                # Check if error is retryable
                if self._is_retryable_error(e):
                    news.content_status = "pending"
                    news.glm_last_error = error_msg[:500]
                    news.glm_retry_count = (news.glm_retry_count or 0) + 1
                    news.glm_next_retry_at = self._get_next_retry_time(news.glm_retry_count)
                    print(f"Retryable error, scheduled retry #{news.glm_retry_count} at {news.glm_next_retry_at}")
                else:
                    # Non-retryable error
                    news.content_status = "failed"
                    news.glm_last_error = error_msg[:500]

                db.commit()

            await asyncio.sleep(0.5)

        return generated_count


news_fetcher = NewsFetcher()
