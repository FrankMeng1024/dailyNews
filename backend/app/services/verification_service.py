"""
News Verification Service

Uses GLM's web search capability to verify news authenticity.
"""
import httpx
import json
import logging
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta

from app.config import settings
from app.models.news import News
from app.services.config_service import DEFAULT_CONFIG

logger = logging.getLogger(__name__)


@dataclass
class VerificationResult:
    """Result of news verification"""
    is_verified: bool           # Whether verification passed
    confidence_score: float     # Confidence score 0-1
    sources_found: int          # Number of related sources found
    matching_claims: int        # Number of matching claims
    total_claims: int           # Total claims checked
    details: Dict[str, Any]     # Detailed verification info
    error: Optional[str] = None # Error message if any


class VerificationService:
    """
    News verification service using GLM web search.

    Verifies news authenticity by:
    1. Extracting key claims from the news
    2. Searching the web for corroborating sources
    3. Analyzing consistency between news and search results
    """

    def __init__(self):
        self.api_key = settings.GLM_API_KEY
        self.api_url = settings.GLM_API_URL
        self.timeout = DEFAULT_CONFIG.get("glm_api_timeout", 60)

    def _get_headers(self) -> Dict[str, str]:
        """Get API request headers"""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    async def _call_glm_with_web_search(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int = 1024
    ) -> Dict[str, Any]:
        """
        Call GLM API with web search tool enabled.

        Args:
            messages: List of message dicts
            max_tokens: Maximum tokens in response

        Returns:
            API response dict
        """
        payload = {
            "model": "glm-4-flash",
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.3,
            "tools": [
                {
                    "type": "web_search",
                    "web_search": {
                        "enable": True,
                        "search_result": True
                    }
                }
            ]
        }

        async with httpx.AsyncClient(timeout=float(self.timeout)) as client:
            response = await client.post(
                self.api_url,
                headers=self._get_headers(),
                json=payload
            )
            response.raise_for_status()
            return response.json()

    async def verify_news(self, news: News) -> VerificationResult:
        """
        Verify a news article's authenticity.

        Args:
            news: News object to verify

        Returns:
            VerificationResult with verification details
        """
        try:
            # Build verification prompt
            title = news.title or ""
            content = (news.original_content or "")[:2000]  # Limit content length
            source = news.source_name or "Unknown"

            prompt = f"""请验证以下新闻的真实性。搜索网络查找相关信息，然后分析这条新闻是否可信。

新闻标题: {title}
新闻来源: {source}
新闻内容摘要: {content[:500]}

请执行以下步骤:
1. 搜索与这条新闻相关的其他来源
2. 检查关键声明是否有其他可靠来源佐证
3. 评估新闻的可信度

请以JSON格式返回结果:
{{
    "is_verified": true/false,
    "confidence_score": 0.0-1.0,
    "sources_found": 数字,
    "matching_claims": 匹配的声明数,
    "total_claims": 总声明数,
    "verification_summary": "简短的验证总结",
    "sources": ["来源1", "来源2"]
}}

只返回JSON，不要其他内容。"""

            messages = [
                {
                    "role": "system",
                    "content": "你是一个专业的新闻事实核查员。你的任务是验证新闻的真实性，通过搜索网络找到佐证或反驳的证据。请客观、严谨地进行验证。"
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ]

            # Call GLM with web search
            response = await self._call_glm_with_web_search(messages, max_tokens=1024)

            # Parse response
            content = response.get("choices", [{}])[0].get("message", {}).get("content", "")

            # Try to extract JSON from response
            result = self._parse_verification_response(content)

            return result

        except httpx.TimeoutException:
            logger.warning(f"Verification timeout for news {news.id}")
            return VerificationResult(
                is_verified=False,
                confidence_score=0.0,
                sources_found=0,
                matching_claims=0,
                total_claims=0,
                details={"reason": "timeout"},
                error="Verification request timed out"
            )
        except Exception as e:
            logger.error(f"Verification error for news {news.id}: {e}")
            return VerificationResult(
                is_verified=False,
                confidence_score=0.0,
                sources_found=0,
                matching_claims=0,
                total_claims=0,
                details={"reason": "error"},
                error=str(e)
            )

    def _parse_verification_response(self, content: str) -> VerificationResult:
        """
        Parse GLM response into VerificationResult.

        Args:
            content: Response content string

        Returns:
            VerificationResult
        """
        try:
            # Try to find JSON in response
            json_start = content.find("{")
            json_end = content.rfind("}") + 1

            if json_start >= 0 and json_end > json_start:
                json_str = content[json_start:json_end]
                data = json.loads(json_str)

                return VerificationResult(
                    is_verified=data.get("is_verified", False),
                    confidence_score=float(data.get("confidence_score", 0.0)),
                    sources_found=int(data.get("sources_found", 0)),
                    matching_claims=int(data.get("matching_claims", 0)),
                    total_claims=int(data.get("total_claims", 0)),
                    details={
                        "summary": data.get("verification_summary", ""),
                        "sources": data.get("sources", [])
                    }
                )
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Failed to parse verification response: {e}")

        # Default result if parsing fails
        return VerificationResult(
            is_verified=False,
            confidence_score=0.0,
            sources_found=0,
            matching_claims=0,
            total_claims=0,
            details={"raw_response": content[:500]},
            error="Failed to parse verification response"
        )

    async def batch_verify(
        self,
        news_list: List[News],
        max_concurrent: int = 3
    ) -> Dict[int, VerificationResult]:
        """
        Verify multiple news articles.

        Args:
            news_list: List of News objects to verify
            max_concurrent: Maximum concurrent verifications

        Returns:
            Dict mapping news ID to VerificationResult
        """
        import asyncio

        results = {}
        semaphore = asyncio.Semaphore(max_concurrent)

        async def verify_with_semaphore(news: News):
            async with semaphore:
                result = await self.verify_news(news)
                results[news.id] = result

        tasks = [verify_with_semaphore(news) for news in news_list]
        await asyncio.gather(*tasks, return_exceptions=True)

        return results

    def get_next_retry_time(self, retry_count: int) -> datetime:
        """
        Calculate next retry time based on retry count.

        Uses exponential backoff: 1, 3, 6, 9, 12 minutes

        Args:
            retry_count: Current retry count

        Returns:
            Next retry datetime
        """
        delays = [1, 3, 6, 9, 12]  # minutes
        delay_minutes = delays[min(retry_count, len(delays) - 1)]
        return datetime.now(timezone.utc) + timedelta(minutes=delay_minutes)


# Singleton instance
_verification_service: Optional[VerificationService] = None


def get_verification_service() -> VerificationService:
    """Get or create verification service instance"""
    global _verification_service
    if _verification_service is None:
        _verification_service = VerificationService()
    return _verification_service
