import httpx
import hashlib
import asyncio
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from app.config import settings
from app.models.news import News


class NewsFetcher:
    """Multi-source AI news fetcher with GLM content generation"""

    def __init__(self):
        self.api_key = settings.NEWS_API_KEY
        self.glm_key = settings.GLM_API_KEY
        self.base_url = settings.NEWS_API_URL

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
                            "publishedAt": datetime.fromtimestamp(story.get("time", 0)).isoformat(),
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
                            "publishedAt": datetime.fromtimestamp(p.get("created_utc", 0)).isoformat(),
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

        # Process in smaller batches for better results
        batch_size = 5
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
                prompt = f"""You are a senior AI technology journalist. Write professional in-depth summaries for each news item.

Requirements:
- Each summary should be 200-300 words, natural and fluent
- Start with the core news event
- Then describe technical/product details and key data
- Analyze relevant background and industry context
- Finally assess the impact on industry and users
- Separate paragraphs with blank lines, no numbering

News list:
{news_list}

Return JSON:
{{"articles": [{{"id": 1, "content": "News summary content...", "score": 8, "ai_related": true}}]}}

Return only JSON."""
            else:  # zh or bilingual (default to Chinese)
                prompt = f"""你是资深科技记者，请为每条AI新闻撰写专业摘要。

写作要求：
- 300-400字，像写新闻稿一样自然流畅
- 直接描述事件，禁止使用"首先"、"其次"、"第一段"、"第二段"等过渡词
- 内容结构：核心事件 → 技术细节 → 行业影响
- 段落自然衔接，无需任何标记或编号

新闻列表：
{news_list}

返回JSON：
{{"articles": [{{"id": 1, "content": "摘要内容...", "score": 8, "ai_related": true}}]}}

只返回JSON。"""

            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    resp = await client.post(
                        "https://open.bigmodel.cn/api/paas/v4/chat/completions",
                        headers={"Authorization": f"Bearer {self.glm_key}", "Content-Type": "application/json"},
                        json={
                            "model": "glm-4-flash",
                            "messages": [{"role": "user", "content": prompt}],
                            "temperature": 0.3
                        }
                    )

                    result = resp.json()

                    if "error" in result:
                        print(f"GLM API error: {result['error']}")
                        continue

                    content = result.get("choices", [{}])[0].get("message", {}).get("content", "")

                    # Parse JSON
                    json_match = re.search(r'\{[\s\S]*\}', content)
                    if json_match:
                        try:
                            analysis = json.loads(json_match.group())

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

    async def fetch_and_save_news(self, db: Session, page_size: int = 50, language: str = "zh", skip_glm: bool = False) -> int:
        """Fetch from all sources, generate content with GLM, and save

        Args:
            db: Database session
            page_size: Number of articles to fetch
            language: 'zh' for Chinese, 'en' for English
            skip_glm: Skip GLM content generation for faster fetch
        """

        # Fetch from all sources in parallel
        print("Fetching from multiple sources...")
        hn_task = self.fetch_hackernews_ai(limit=15)
        reddit_task = self.fetch_reddit_ai(limit=10)
        newsapi_task = self.fetch_newsapi_ai(page_size=20)

        hn_articles, reddit_articles, newsapi_articles = await asyncio.gather(
            hn_task, reddit_task, newsapi_task
        )

        print(f"Fetched: HN={len(hn_articles)}, Reddit={len(reddit_articles)}, NewsAPI={len(newsapi_articles)}")

        # Combine all articles
        all_articles = hn_articles + reddit_articles + newsapi_articles

        if not all_articles:
            print("No articles fetched")
            return 0

        # Use GLM to generate content (or skip for quick mode)
        if skip_glm:
            print("Skipping GLM content generation (quick mode)")
            enriched_articles = all_articles
        else:
            print(f"Generating content with GLM (language={language})...")
            enriched_articles = await self.glm_generate_content(all_articles, language=language)
            print(f"Content generated for {len(enriched_articles)} articles")

        # Save to database
        saved_count = 0
        skipped_count = 0
        for article in enriched_articles:
            external_id = self.generate_external_id(article)
            if db.query(News).filter(News.external_id == external_id).first():
                skipped_count += 1
                continue

            published_at = article.get("publishedAt")
            try:
                if published_at:
                    published_at = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
                else:
                    published_at = datetime.utcnow()
            except:
                published_at = datetime.utcnow()

            glm_score = article.get("glm_score", 0.5)

            # Use generated content, fallback to description
            content = article.get("generated_content") or article.get("description") or ""

            news = News(
                external_id=external_id,
                title=article.get("title", "")[:512],
                source_name=article.get("source", "Unknown")[:128],
                source_url=article.get("url", "")[:1024],
                author=article.get("author", "")[:256] if article.get("author") else None,
                content=content,
                summary=article.get("description", "")[:500] if article.get("description") else None,
                image_url=None,  # No images
                published_at=published_at,
                glm_score=glm_score,
                final_score=glm_score,
                category="ai" if article.get("ai_related", True) else "tech"
            )
            db.add(news)
            saved_count += 1

        db.commit()
        print(f"Saved {saved_count} new articles, skipped {skipped_count} duplicates")
        return (saved_count, skipped_count)


news_fetcher = NewsFetcher()
