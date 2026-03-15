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
        翻译文本为中文（旧方法，保留兼容）

        Args:
            text: 要翻译的文本
            context: 上下文信息（可选）

        Returns:
            翻译后的中文文本
        """
        # 使用新的标题生成方法
        return await self.generate_chinese_title(text, context)

    async def generate_chinese_title(self, title: str, summary: str = "") -> Optional[str]:
        """
        为英文新闻生成中文标题

        不是简单翻译，而是根据中文新闻标题习惯重新起标题

        Args:
            title: 英文标题
            summary: 文章摘要（可选，用于理解上下文）

        Returns:
            中文标题
        """
        prompt = f"""你是资深中文科技编辑。请为以下英文新闻起一个中文标题。

要求：
1. 长度：15-35个中文字符（必须遵守）
2. 风格：简洁有力，像36氪、虎嗅的标题
3. 准确传达核心信息，不遗漏关键词
4. AI/GPT/LLM/Claude 等术语可保留英文
5. 只输出标题，不要解释，不要引号

英文标题：{title}
"""
        if summary:
            # 只取摘要前200字符作为参考
            prompt += f"\n参考摘要：{summary[:200]}"

        prompt += "\n\n中文标题："

        result = await self.call(prompt, max_tokens=100, temperature=0.3)
        if result:
            # 清理可能的引号和多余空白
            result = result.strip().strip('"\'「」『』《》""''')
            # 去除可能的前缀
            for prefix in ['中文标题：', '中文标题:', '标题：', '标题:']:
                if result.startswith(prefix):
                    result = result[len(prefix):].strip()
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
        prompt = f"""你是资深科技记者。请根据以下新闻内容，撰写一篇中文摘要。

【字数要求 - 最重要】
必须写 400-600 字（约 4-6 段），不能少于 400 字！

【内容要求】
1. 保留原文中的具体数字、百分比、时间（如 "50%"、"$25M"、"300倍"）
2. 保留专业术语（如 MTTR、CI/CD、LLM、Transformer）
3. 不要重复同一观点

【结构】
第一段：核心结论 + 关键数字
第二段：技术细节或产品特性
第三段：具体数据或案例
第四段：背景意义
第五段（可选）：后续展望

【风格】
- 36氪/虎嗅风格，简洁有力
- 每句不超过 25 字
- 避免空洞表述

标题：{title}

原文：
{original_content[:4000]}

请直接输出摘要正文（不要输出"标题"或"摘要"等前缀）："""

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

    # ==================== 三阶段精炼 v2 ====================

    async def extract_key_points(self, title: str, content: str) -> dict:
        """
        阶段1：提取关键信息（Extractive）

        识别原文中 20% 的核心信息，提取所有关键数据

        Args:
            title: 文章标题
            content: 原始内容

        Returns:
            {"key_facts": [...], "key_data": [...], "key_quotes": [...]}
        """
        prompt = f"""你是资深科技编辑。请从以下文章中提取关键信息。

【任务】
识别文章中最重要的 20% 信息（80/20 原则）

【提取内容】
1. key_facts: 3-5 条核心事实（每条 1 句话）
2. key_data: 所有重要数字（百分比、金额、时间、数量等）
3. key_quotes: 1-2 条关键引用或观点

【重要】
- 只提取原文明确提到的信息
- 数字必须与原文完全一致
- 不要推测或补充

标题：{title}

原文：
{content[:6000]}

返回 JSON 格式：
{{"key_facts": ["事实1", "事实2", ...], "key_data": ["$10M", "50%", ...], "key_quotes": ["引用1", ...]}}

只返回 JSON："""

        result = await self.call(prompt, max_tokens=1000, temperature=0.1)
        if not result:
            return {"key_facts": [], "key_data": [], "key_quotes": []}

        try:
            json_match = re.search(r'\{[\s\S]*\}', result)
            if json_match:
                data = json.loads(json_match.group())
                return {
                    "key_facts": data.get("key_facts", []),
                    "key_data": data.get("key_data", []),
                    "key_quotes": data.get("key_quotes", [])
                }
        except json.JSONDecodeError:
            pass

        return {"key_facts": [], "key_data": [], "key_quotes": []}

    async def refine_content_v2(
        self,
        title: str,
        content: str,
        key_points: dict,
        source_type: str = "news"
    ) -> Optional[str]:
        """
        阶段2：基于关键信息精炼（Abstractive）

        Args:
            title: 文章标题
            content: 原始内容
            key_points: 阶段1提取的关键信息
            source_type: 内容类型 (blog/news/paper/discussion)

        Returns:
            精炼后的中文内容
        """
        # 格式化关键信息
        key_facts_str = "\n".join(f"- {f}" for f in key_points.get("key_facts", []))
        key_data_str = ", ".join(key_points.get("key_data", [])) or "无"
        key_quotes_str = "\n".join(f"- {q}" for q in key_points.get("key_quotes", []))

        prompt = f"""你是资深科技记者。请基于以下关键信息，撰写一篇中文摘要。

【禁止杜撰 - 最重要】
1. 所有数字必须来自「关键数据」，禁止编造
2. 如果关键数据为空，不要使用任何具体数字
3. 不确定的信息用"据称"、"约"等词修饰
4. 宁可省略，也不要杜撰

【关键事实】
{key_facts_str or "无"}

【关键数据】
{key_data_str}

【关键引用】
{key_quotes_str or "无"}

【字数要求】
400-600 字（约 4-6 段）

【结构】
第一段：核心结论 + 关键数字（如有）
第二段：技术细节或产品特性
第三段：具体数据或案例（如有）
第四段：背景意义
第五段（可选）：后续展望

【风格】
- 36氪/虎嗅风格，简洁有力
- 每句不超过 25 字
- 保留专业术语（AI、LLM、GPT 等）

标题：{title}

原文参考：
{content[:3000]}

请直接输出摘要正文："""

        return await self.call(prompt, max_tokens=2048, temperature=0.3)

    async def verify_refinement(
        self,
        original_content: str,
        refined_content: str,
        key_points: dict
    ) -> dict:
        """
        阶段3：验证精炼质量

        检查精炼内容是否与原文一致，是否有杜撰

        Args:
            original_content: 原始内容
            refined_content: 精炼后的内容
            key_points: 阶段1提取的关键信息

        Returns:
            {"is_valid": bool, "issues": [...], "corrected_content": str or None}
        """
        key_data_str = ", ".join(key_points.get("key_data", [])) or "无"

        prompt = f"""你是内容审核专家。请检查以下精炼内容是否存在问题。

【检查重点】
1. 精炼内容中的数字是否都在「原文关键数据」中？
2. 是否有杜撰的信息（原文没有提到的）？
3. 是否遗漏了重要信息？

【原文关键数据】
{key_data_str}

【精炼内容】
{refined_content}

【原文片段】
{original_content[:2000]}

返回 JSON 格式：
{{
  "is_valid": true/false,
  "issues": ["问题1", "问题2", ...],
  "has_fabrication": true/false,
  "fabricated_data": ["杜撰的数据1", ...]
}}

只返回 JSON："""

        result = await self.call(prompt, max_tokens=500, temperature=0.1)
        if not result:
            return {"is_valid": True, "issues": [], "has_fabrication": False}

        try:
            json_match = re.search(r'\{[\s\S]*\}', result)
            if json_match:
                data = json.loads(json_match.group())
                return {
                    "is_valid": data.get("is_valid", True),
                    "issues": data.get("issues", []),
                    "has_fabrication": data.get("has_fabrication", False),
                    "fabricated_data": data.get("fabricated_data", [])
                }
        except json.JSONDecodeError:
            pass

        return {"is_valid": True, "issues": [], "has_fabrication": False}

    async def refine_content_three_stage(
        self,
        title: str,
        content: str,
        source_type: str = "news"
    ) -> Optional[str]:
        """
        三阶段精炼主入口

        Args:
            title: 文章标题
            content: 原始内容
            source_type: 内容类型

        Returns:
            精炼后的中文内容
        """
        # 阶段1：提取关键信息
        key_points = await self.extract_key_points(title, content)
        logger.info(f"Stage 1: extracted {len(key_points.get('key_facts', []))} facts, "
                   f"{len(key_points.get('key_data', []))} data points")

        # 阶段2：精炼改写
        refined = await self.refine_content_v2(title, content, key_points, source_type)
        if not refined:
            logger.warning("Stage 2 failed: no refined content")
            return None

        # 阶段3：验证校对
        verification = await self.verify_refinement(content, refined, key_points)

        if verification.get("has_fabrication"):
            logger.warning(f"Stage 3: fabrication detected: {verification.get('fabricated_data')}")
            # 如果检测到杜撰，重新精炼（更严格的 prompt）
            refined = await self._refine_strict(title, content, key_points, verification)

        logger.info(f"Three-stage refinement complete: {len(refined)} chars")
        return refined

    async def _refine_strict(
        self,
        title: str,
        content: str,
        key_points: dict,
        verification: dict
    ) -> Optional[str]:
        """严格模式重新精炼（检测到杜撰后使用）"""
        fabricated = verification.get("fabricated_data", [])
        key_data_str = ", ".join(key_points.get("key_data", [])) or "无"

        prompt = f"""你是资深科技记者。请重新撰写摘要，修正以下问题。

【发现的问题】
以下数据是杜撰的，原文中没有：{fabricated}

【允许使用的数据】
只能使用这些数据：{key_data_str}

【要求】
- 400-600 字
- 不要使用任何不在「允许使用的数据」中的数字
- 如果没有数据，就不要写具体数字

标题：{title}

原文：
{content[:3000]}

请直接输出修正后的摘要："""

        return await self.call(prompt, max_tokens=2048, temperature=0.2)

    async def verify_content_validity(self, title: str, content: str) -> dict:
        """
        验证抓取的内容是否为真正的文章原文（AI 验证备案）

        Args:
            title: 文章标题
            content: 抓取的内容

        Returns:
            {"is_valid": bool, "confidence": float, "reason": str}
        """
        prompt = f"""请判断以下抓取的内容是否为真正的文章原文。

标题：{title}

抓取内容（前1000字符）：
{content[:1000]}

请判断：
1. 这是否是文章的实际内容（而非网站模板、导航菜单、错误页面、登录提示、广告等）？
2. 内容是否与标题相关？
3. 内容是否完整有意义（而非片段或乱码）？

返回JSON格式：
{{"is_valid": true/false, "confidence": 0.8, "reason": "简短理由"}}

只返回JSON。"""

        result = await self.call(prompt, max_tokens=200, temperature=0.1)
        if not result:
            # API 调用失败，保守起见返回无效
            return {"is_valid": False, "confidence": 0.0, "reason": "API call failed"}

        try:
            json_match = re.search(r'\{[\s\S]*\}', result)
            if json_match:
                data = json.loads(json_match.group())
                return {
                    "is_valid": data.get("is_valid", False),
                    "confidence": data.get("confidence", 0.5),
                    "reason": data.get("reason", "")
                }
        except json.JSONDecodeError:
            pass

        return {"is_valid": False, "confidence": 0.0, "reason": "Parse failed"}

    async def evaluate_refinement_quality(
        self,
        original_content: str,
        refined_content: str,
        title: str = ""
    ) -> dict:
        """
        评估精炼质量（2/8 原则）

        Args:
            original_content: 原始内容
            refined_content: 精炼后的内容
            title: 文章标题（可选）

        Returns:
            {
                "scores": {"coverage": 8, "extraction": 7, "readability": 9, "accuracy": 8},
                "total": 8.0,
                "reason": "简短评价",
                "issues": ["问题1", "问题2"]
            }
        """
        prompt = f"""你是内容质量评估专家。请对比原文和精炼内容，给出评分。

【评分标准】
1. coverage (核心信息覆盖度 0-10): 原文核心观点、关键数据是否保留
2. extraction (精华提取度 0-10): 是否遵循2/8原则，去除冗余，信息密度高
3. readability (可读性 0-10): 用户能否快速理解，语言简洁，结构清晰
4. accuracy (准确性 0-10): 是否有杜撰数据或误导性表述

【标题】
{title}

【原文】（前3000字符）
{original_content[:3000]}

【精炼内容】
{refined_content}

【输出格式】
返回 JSON：
{{"scores": {{"coverage": 8, "extraction": 7, "readability": 9, "accuracy": 8}}, "total": 8.0, "reason": "简短评价", "issues": ["问题1", "问题2"]}}

只返回 JSON："""

        result = await self.call(prompt, max_tokens=500, temperature=0.1)
        if not result:
            return {
                "scores": {"coverage": 0, "extraction": 0, "readability": 0, "accuracy": 0},
                "total": 0,
                "reason": "API call failed",
                "issues": ["API 调用失败"]
            }

        try:
            # 移除 markdown 代码块标记
            cleaned = re.sub(r'```json\s*', '', result)
            cleaned = re.sub(r'```\s*', '', cleaned)

            json_match = re.search(r'\{[\s\S]*\}', cleaned)
            if json_match:
                data = json.loads(json_match.group())
                scores = data.get("scores", {})
                # 计算总分（如果没有提供）
                if "total" not in data and scores:
                    total = sum(scores.values()) / len(scores)
                else:
                    total = data.get("total", 0)
                return {
                    "scores": {
                        "coverage": scores.get("coverage", 0),
                        "extraction": scores.get("extraction", 0),
                        "readability": scores.get("readability", 0),
                        "accuracy": scores.get("accuracy", 0)
                    },
                    "total": total,
                    "reason": data.get("reason", ""),
                    "issues": data.get("issues", [])
                }
        except json.JSONDecodeError:
            pass

        return {
            "scores": {"coverage": 0, "extraction": 0, "readability": 0, "accuracy": 0},
            "total": 0,
            "reason": "Parse failed",
            "issues": ["JSON 解析失败"]
        }


# 全局单例
glm_client = GLMClient(max_concurrent=3)
