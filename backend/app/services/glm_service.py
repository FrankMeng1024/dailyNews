import httpx
import json
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session

from app.config import settings
from app.models.news import News


class GLMService:
    """Service for Zhipu GLM API integration"""

    def __init__(self):
        self.api_key = settings.GLM_API_KEY
        self.api_url = settings.GLM_API_URL
        self.model = settings.GLM_MODEL

    def _get_headers(self) -> Dict[str, str]:
        """Get API request headers"""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    async def _call_api(self, messages: List[Dict[str, str]], max_tokens: int = 1024, model: str = None) -> str:
        """
        Call GLM API with messages

        Args:
            messages: List of message dicts with role and content
            max_tokens: Maximum tokens in response
            model: Model to use (defaults to glm-4.7-flash - free model)

        Returns:
            Response content string
        """
        payload = {
            "model": model or "glm-4.7-flash",  # Use latest free model
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.7
        }

        async with httpx.AsyncClient(timeout=1800.0) as client:
            response = await client.post(
                self.api_url,
                headers=self._get_headers(),
                json=payload
            )
            response.raise_for_status()
            data = response.json()

            return data["choices"][0]["message"]["content"]

    async def score_news_importance(self, news_list: List[News]) -> Dict[int, float]:
        """
        Score news articles for importance using GLM

        Args:
            news_list: List of News objects to score

        Returns:
            Dict mapping news ID to importance score (0-1)
        """
        if not news_list:
            return {}

        # Prepare news summaries for scoring
        news_texts = []
        for i, news in enumerate(news_list):
            news_texts.append(f"{i+1}. {news.title}")

        prompt = f"""You are an AI news analyst. Rate the importance of each news article below on a scale of 0 to 1.
Consider factors like:
- Breakthrough or significant advancement in AI
- Impact on industry or society
- Relevance to current AI trends
- Credibility of the source

News articles:
{chr(10).join(news_texts)}

Respond with ONLY a JSON object mapping article numbers to scores, like:
{{"1": 0.85, "2": 0.72, "3": 0.45}}

Be strict - only truly important news should score above 0.7."""

        messages = [
            {"role": "system", "content": "You are an AI news importance scorer. Respond only with valid JSON."},
            {"role": "user", "content": prompt}
        ]

        try:
            response = await self._call_api(messages, max_tokens=512)
            # Parse JSON response
            scores_raw = json.loads(response.strip())

            # Map back to news IDs
            scores = {}
            for i, news in enumerate(news_list):
                score_key = str(i + 1)
                if score_key in scores_raw:
                    scores[news.id] = float(scores_raw[score_key])

            return scores

        except Exception as e:
            # Return default scores on error
            return {news.id: 0.5 for news in news_list}

    async def generate_summary(self, content: str, max_length: int = 200) -> str:
        """
        Generate a summary of news content

        Args:
            content: Full news content
            max_length: Maximum summary length in characters

        Returns:
            Summary string
        """
        prompt = f"""Summarize the following news article in {max_length} characters or less.
Focus on the key points and main takeaway.

Article:
{content[:2000]}

Summary:"""

        messages = [
            {"role": "system", "content": "You are a concise news summarizer."},
            {"role": "user", "content": prompt}
        ]

        try:
            return await self._call_api(messages, max_tokens=256)
        except Exception as e:
            return content[:max_length] + "..." if len(content) > max_length else content

    async def translate_title(self, title: str) -> str:
        """
        Translate English news title to Chinese

        Args:
            title: English news title

        Returns:
            Chinese translated title
        """
        prompt = f"""将以下英文新闻标题翻译成简洁的中文，保持新闻标题风格，不要添加额外内容：

{title}

只输出翻译结果，不要其他内容。"""

        messages = [
            {"role": "system", "content": "你是一位专业的新闻翻译。"},
            {"role": "user", "content": prompt}
        ]

        try:
            result = await self._call_api(messages, max_tokens=128)
            return result.strip()
        except Exception as e:
            return title  # Return original on error

    async def translate_titles_batch(self, titles: List[str]) -> List[str]:
        """
        Translate multiple English titles to Chinese in one API call

        Args:
            titles: List of English titles

        Returns:
            List of Chinese translated titles
        """
        if not titles:
            return []

        titles_text = "\n".join([f"{i+1}. {t}" for i, t in enumerate(titles)])

        prompt = f"""将以下英文新闻标题翻译成简洁的中文，保持新闻标题风格。

{titles_text}

输出格式（JSON数组）：
["翻译1", "翻译2", ...]

只输出JSON数组，不要其他内容。"""

        messages = [
            {"role": "system", "content": "你是一位专业的新闻翻译。只输出JSON数组。"},
            {"role": "user", "content": prompt}
        ]

        try:
            response = await self._call_api(messages, max_tokens=1024)
            response = response.strip()
            if response.startswith("```"):
                response = response.split("```")[1]
                if response.startswith("json"):
                    response = response[4:]
            return json.loads(response)
        except Exception as e:
            return titles  # Return originals on error

    async def generate_dialogue_script(
        self,
        news_list: List[News],
        language: str = "zh"
    ) -> List[Dict[str, str]]:
        """
        Generate a two-person dialogue script discussing the news

        Args:
            news_list: List of news articles to discuss
            language: Output language (zh, en, bilingual)

        Returns:
            List of dialogue turns with speaker and text
        """
        import logging
        logger = logging.getLogger(__name__)

        # Prepare news content - use refined content (news.content) with higher limit
        news_content = []
        for i, news in enumerate(news_list):
            # Prefer refined content, fallback to original_content, then summary
            content = news.content or news.original_content or news.summary or ""
            # Use up to 2000 chars per article for better dialogue quality
            content_preview = content[:2000] if content else ""
            news_content.append(f"新闻 {i+1}: {news.title}\n{content_preview}")
            # Debug logging
            logger.info(f"[Dialogue] News {i+1}: title={news.title[:50]}, content_status={news.content_status}, content_len={len(content)}")

        lang_instruction = {
            "zh": "用中文生成对话",
            "en": "Generate dialogue in English",
            "bilingual": "Generate dialogue mixing Chinese and English naturally"
        }.get(language, "用中文生成对话")

        prompt = f"""你是一位专业的播客脚本作家。请根据以下新闻内容，创作一段两人对话讨论。

主持人设定：
- 小雅（女）：善于分析，提出有洞察力的问题
- 小明（男）：善于解释，分享观点和见解

{lang_instruction}

新闻内容：
{chr(10).join(news_content)}

要求：
1. 开场简短介绍今天要讨论的话题
2. 深入讨论每条新闻的核心内容、技术细节、行业影响
3. 两人有来有往，自然对话，不要生硬
4. 结尾总结要点，展望未来
5. 对话时长约3-5分钟（约800-1200字）

输出格式（JSON数组）：
[
  {{"speaker": "小雅", "text": "..."}},
  {{"speaker": "小明", "text": "..."}},
  ...
]

只输出JSON，不要其他内容。"""

        messages = [
            {"role": "system", "content": "You are a podcast script writer. Output valid JSON only."},
            {"role": "user", "content": prompt}
        ]

        try:
            # Retry logic for rate limiting
            max_retries = 3
            response = None
            last_error = None

            for attempt in range(max_retries):
                try:
                    response = await self._call_api(messages, max_tokens=4096)
                    break
                except Exception as e:
                    last_error = e
                    if '429' in str(e) and attempt < max_retries - 1:
                        logger.warning(f"[Dialogue] Rate limited, waiting 5s before retry {attempt + 2}/{max_retries}")
                        import asyncio
                        await asyncio.sleep(5)
                    else:
                        raise Exception(f"GLM API调用失败: {str(e) or type(e).__name__}")

            # Check if we got a response
            if response is None:
                raise Exception(f"GLM API调用失败，已重试{max_retries}次: {str(last_error) or '未知错误'}")

            # Clean response and parse JSON
            response = response.strip()
            if response.startswith("```"):
                response = response.split("```")[1]
                if response.startswith("json"):
                    response = response[4:]

            dialogue = json.loads(response)
            logger.info(f"[Dialogue] Generated {len(dialogue)} turns")
            return dialogue

        except json.JSONDecodeError as e:
            logger.error(f"[Dialogue] JSON parse error: {e}")
            raise Exception(f"对话脚本解析失败: AI返回的格式不正确")
        except Exception as e:
            logger.error(f"[Dialogue] GLM error: {e}")
            error_msg = str(e) or "未知错误"
            if "对话脚本" in error_msg or "GLM" in error_msg:
                raise  # Already has user-friendly message
            raise Exception(f"对话脚本生成失败: {error_msg}")

    async def score_and_update_news(self, db: Session, news_list: List[News]) -> int:
        """
        Score news and update database

        Args:
            db: Database session
            news_list: List of news to score

        Returns:
            Number of news items updated
        """
        if not news_list:
            return 0

        # Get scores from GLM
        scores = await self.score_news_importance(news_list)

        # Update news records
        updated = 0
        for news in news_list:
            if news.id in scores:
                news.glm_score = scores[news.id]
                news.calculate_final_score()
                updated += 1

        db.commit()
        return updated


glm_service = GLMService()
