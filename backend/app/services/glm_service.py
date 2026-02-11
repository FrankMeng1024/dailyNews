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

    async def _call_api(self, messages: List[Dict[str, str]], max_tokens: int = 1024) -> str:
        """
        Call GLM API with messages

        Args:
            messages: List of message dicts with role and content
            max_tokens: Maximum tokens in response

        Returns:
            Response content string
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.7
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
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
        # Prepare news content
        news_content = []
        for i, news in enumerate(news_list):
            news_content.append(f"Article {i+1}: {news.title}\n{news.summary or news.content[:500]}")

        lang_instruction = {
            "zh": "用中文生成对话",
            "en": "Generate dialogue in English",
            "bilingual": "Generate dialogue mixing Chinese and English naturally"
        }.get(language, "用中文生成对话")

        prompt = f"""Create a natural discussion between two hosts about these AI news articles.
Host A (Alice/小雅) is female, analytical and asks insightful questions.
Host B (Bob/小明) is male, provides explanations and shares opinions.

{lang_instruction}

News to discuss:
{chr(10).join(news_content)}

Create an engaging 3-5 minute dialogue that:
1. Opens with a brief introduction
2. Discusses each news item with analysis
3. Includes back-and-forth discussion
4. Ends with a summary/conclusion

Format as JSON array:
[
  {{"speaker": "Alice", "text": "..."}},
  {{"speaker": "Bob", "text": "..."}},
  ...
]"""

        messages = [
            {"role": "system", "content": "You are a podcast script writer. Output valid JSON only."},
            {"role": "user", "content": prompt}
        ]

        try:
            response = await self._call_api(messages, max_tokens=4096)
            # Clean response and parse JSON
            response = response.strip()
            if response.startswith("```"):
                response = response.split("```")[1]
                if response.startswith("json"):
                    response = response[4:]

            return json.loads(response)

        except Exception as e:
            # Return minimal dialogue on error
            return [
                {"speaker": "Alice", "text": "今天我们来讨论一些AI新闻。" if language == "zh" else "Let's discuss some AI news today."},
                {"speaker": "Bob", "text": "好的，让我们开始吧。" if language == "zh" else "Sure, let's get started."}
            ]

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
