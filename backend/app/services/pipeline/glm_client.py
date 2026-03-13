"""
GLM Client - GLM API 客户端（带并发控制）

使用 asyncio.Semaphore 限制并发请求数，避免 API 限流
"""

import asyncio
import httpx
import logging
import re
import json
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)


class GLMClient:
    """GLM API 客户端，带并发控制"""

    def __init__(self, max_concurrent: int = 3):
        """
        初始化 GLM 客户端

        Args:
            max_concurrent: 最大并发请求数
        """
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.api_key = settings.GLM_API_KEY
        self.api_url = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
        self.model = "glm-4-flash"

    async def call(
        self,
        prompt: str,
        max_tokens: int = 2048,
        temperature: float = 0.3,
        timeout: float = 60.0
    ) -> Optional[str]:
        """
        调用 GLM API

        Args:
            prompt: 提示词
            max_tokens: 最大生成 token 数
            temperature: 温度参数
            timeout: 超时时间（秒）

        Returns:
            生成的文本，失败返回 None
        """
        if not self.api_key:
            logger.warning("GLM API key not configured")
            return None

        async with self.semaphore:
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.post(
                        self.api_url,
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json"
                        },
                        json={
                            "model": self.model,
                            "messages": [{"role": "user", "content": prompt}],
                            "temperature": temperature,
                            "max_tokens": max_tokens
                        }
                    )

                    result = resp.json()

                    if "error" in result:
                        logger.error(f"GLM API error: {result['error']}")
                        return None

                    content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
                    return content if content else None

            except httpx.TimeoutException:
                logger.error("GLM API timeout")
                return None
            except Exception as e:
                logger.error(f"GLM API error: {e}")
                return None

    async def translate(self, text: str, context: str = "") -> Optional[str]:
        """
        翻译文本为中文

        Args:
            text: 要翻译的文本
            context: 上下文信息（可选）

        Returns:
            翻译后的中文文本
        """
        prompt = f"""请将以下英文标题翻译成中文，要求：
1. 保持原意，语句通顺
2. 专业术语保持准确
3. 只返回翻译结果，不要解释

标题：{text}
"""
        if context:
            prompt += f"\n上下文：{context[:500]}"

        result = await self.call(prompt, max_tokens=256, temperature=0.1)
        if result:
            # 清理可能的引号和多余空白
            result = result.strip().strip('"\'')
        return result

    async def refine_content(self, title: str, original_content: str) -> Optional[str]:
        """
        精炼文章内容

        Args:
            title: 文章标题
            original_content: 原始内容

        Returns:
            精炼后的中文内容
        """
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

标题：{title}

原文内容：
{original_content[:4000]}

请直接输出摘要内容，不需要JSON格式，不需要标题。"""

        return await self.call(prompt, max_tokens=2048, temperature=0.3)

    async def verify_ai_relevance(self, title: str, content: str) -> dict:
        """
        验证内容是否与 AI 相关

        Args:
            title: 文章标题
            content: 文章内容

        Returns:
            {"is_ai_related": bool, "relevance_score": float, "reason": str}
        """
        prompt = f"""请判断以下内容是否与人工智能(AI)相关。

标题：{title}
内容摘要：{content[:500]}

要求：
1. 判断是否真正与AI相关（不是仅仅提到AI，而是核心内容就是关于AI的）
2. 给出相关性评分（0-10分，10分表示高度相关）

返回JSON格式：
{{"is_ai_related": true/false, "relevance_score": 8, "reason": "简短理由"}}

只返回JSON。"""

        result = await self.call(prompt, max_tokens=200, temperature=0.1)
        if not result:
            return {"is_ai_related": True, "relevance_score": 0.5, "reason": "API call failed"}

        try:
            json_match = re.search(r'\{[\s\S]*\}', result)
            if json_match:
                data = json.loads(json_match.group())
                return {
                    "is_ai_related": data.get("is_ai_related", True),
                    "relevance_score": data.get("relevance_score", 5) / 10.0,
                    "reason": data.get("reason", "")
                }
        except json.JSONDecodeError:
            pass

        return {"is_ai_related": True, "relevance_score": 0.5, "reason": "Parse failed"}


# 全局单例
glm_client = GLMClient(max_concurrent=3)
